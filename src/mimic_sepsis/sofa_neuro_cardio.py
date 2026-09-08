"""Pure preparation functions for neurologic and cardiovascular SOFA inputs."""

from __future__ import annotations

import re

import pandas as pd


GCS_ITEMS = {220739: "eye", 223900: "verbal", 223901: "motor"}
GCS_LIMITS = {"eye": (1, 4), "verbal": (1, 5), "motor": (1, 6)}
MAP_ITEMID = 220052
VASOACTIVE_ITEMS = {
    221906: "norepinephrine",
    221289: "epinephrine",
    221662: "dopamine",
    221653: "dobutamine",
}


def _require(frame: pd.DataFrame, columns: set[str], name: str) -> None:
    missing = sorted(columns - set(frame.columns))
    if missing:
        raise ValueError(f"{name} is missing columns: {', '.join(missing)}")


def _numeric_gcs(value: object) -> float | None:
    """Extract a numeric GCS category without interpreting free text clinically."""
    if pd.isna(value):
        return None
    match = re.search(r"(?<!\d)([1-6])(?:\.0)?(?!\d)", str(value))
    return float(match.group(1)) if match else None


def normalize_gcs_events(events: pd.DataFrame) -> pd.DataFrame:
    """Normalize MIMIC GCS component rows and expose intubated verbal entries.

    ``value`` is retained for detecting explicit ET/tracheostomy categories;
    ``valuenum`` is preferred when present. Invalid component categories and
    invalid timestamps are discarded.
    """
    _require(
        events,
        {"stay_id", "charttime", "itemid", "value", "valuenum"},
        "events",
    )
    result = events.loc[events["itemid"].isin(GCS_ITEMS)].copy()
    result["charttime"] = pd.to_datetime(result["charttime"], errors="coerce")
    result["component"] = result["itemid"].map(GCS_ITEMS)
    text = result["value"].fillna("").astype(str)
    result["intubated"] = (
        result["component"].eq("verbal")
        & text.str.contains(r"\b(?:ET|ETT|Trach|Intubat)", case=False, regex=True)
    )
    numeric = pd.to_numeric(result["valuenum"], errors="coerce")
    extracted = result["value"].map(_numeric_gcs)
    result["component_value"] = numeric.fillna(extracted)
    valid = pd.Series(False, index=result.index)
    for component, (low, high) in GCS_LIMITS.items():
        valid |= result["component"].eq(component) & result["component_value"].between(
            low, high, inclusive="both"
        )
    result = result.loc[result["charttime"].notna() & valid].copy()
    return result[
        ["stay_id", "charttime", "component", "component_value", "intubated"]
    ].sort_values(["stay_id", "charttime", "component"]).reset_index(drop=True)


def reconstruct_gcs(
    events: pd.DataFrame, *, contemporaneous_minutes: float = 60
) -> pd.DataFrame:
    """Build complete GCS observations from components close in time.

    Every observed component time is an anchor. For each component the nearest
    measurement in the same stay is selected within the symmetric tolerance.
    Duplicate reconstructions are collapsed. No component is carried beyond
    that tolerance, preventing a total assembled from unrelated examinations.
    """
    if contemporaneous_minutes < 0:
        raise ValueError("contemporaneous_minutes must be non-negative")
    normalized = normalize_gcs_events(events)
    columns = [
        "stay_id", "charttime", "gcs_eye", "gcs_verbal", "gcs_motor",
        "gcs_total", "verbal_intubated", "component_span_minutes",
    ]
    if normalized.empty:
        return pd.DataFrame(columns=columns)

    if contemporaneous_minutes == 0:
        values = normalized.pivot_table(
            index=["stay_id", "charttime"], columns="component",
            values="component_value", aggfunc="last",
        )
        complete = values.dropna(subset=["eye", "verbal", "motor"]).reset_index()
        if complete.empty:
            return pd.DataFrame(columns=columns)
        intubated = (
            normalized.loc[normalized["component"].eq("verbal")]
            .groupby(["stay_id", "charttime"])["intubated"].max()
        )
        complete["gcs_eye"] = complete["eye"].astype(int)
        complete["gcs_verbal"] = complete["verbal"].astype(int)
        complete["gcs_motor"] = complete["motor"].astype(int)
        complete["gcs_total"] = complete[["gcs_eye", "gcs_verbal", "gcs_motor"]].sum(axis=1)
        complete["verbal_intubated"] = [
            bool(intubated.get((row.stay_id, row.charttime), False))
            for row in complete.itertuples(index=False)
        ]
        complete["component_span_minutes"] = 0.0
        return complete[columns].sort_values(["stay_id", "charttime"]).reset_index(drop=True)

    tolerance = pd.to_timedelta(float(contemporaneous_minutes) * 60, unit="s")
    rows: list[dict[str, object]] = []
    for stay_id, stay in normalized.groupby("stay_id", sort=True):
        anchors = stay["charttime"].drop_duplicates().sort_values()
        by_component = {
            component: part.sort_values("charttime")
            for component, part in stay.groupby("component")
        }
        for anchor in anchors:
            selected: dict[str, pd.Series] = {}
            for component in ("eye", "verbal", "motor"):
                candidates = by_component.get(component)
                if candidates is None:
                    break
                distance = (candidates["charttime"] - anchor).abs()
                eligible = candidates.loc[distance <= tolerance]
                if eligible.empty:
                    break
                # Stable tie-break: prefer the earlier examination.
                chosen = eligible.assign(_distance=distance.loc[eligible.index]).sort_values(
                    ["_distance", "charttime"]
                ).iloc[0]
                selected[component] = chosen
            if len(selected) != 3:
                continue
            times = [selected[name]["charttime"] for name in ("eye", "verbal", "motor")]
            values = {
                name: int(selected[name]["component_value"])
                for name in ("eye", "verbal", "motor")
            }
            rows.append(
                {
                    "stay_id": stay_id,
                    # Canonical availability time: the total did not exist
                    # until the last selected component was charted.
                    "charttime": max(times),
                    "gcs_eye": values["eye"],
                    "gcs_verbal": values["verbal"],
                    "gcs_motor": values["motor"],
                    "gcs_total": sum(values.values()),
                    "verbal_intubated": bool(selected["verbal"]["intubated"]),
                    "component_span_minutes": (
                        max(times) - min(times)
                    ).total_seconds() / 60,
                }
            )
    result = pd.DataFrame(rows, columns=columns)
    if result.empty:
        return result
    return result.drop_duplicates(
        [
            "stay_id", "charttime", "gcs_eye", "gcs_verbal", "gcs_motor",
            "verbal_intubated",
        ]
    ).sort_values(["stay_id", "charttime"]).reset_index(drop=True)


def normalize_map_events(events: pd.DataFrame) -> pd.DataFrame:
    """Return valid invasive/non-invasive MIMIC MAP observations (mmHg)."""
    _require(events, {"stay_id", "charttime", "itemid", "valuenum"}, "events")
    result = events.loc[events["itemid"].eq(MAP_ITEMID)].copy()
    result["charttime"] = pd.to_datetime(result["charttime"], errors="coerce")
    result["map_mmhg"] = pd.to_numeric(result["valuenum"], errors="coerce")
    result = result.loc[
        result["charttime"].notna() & result["map_mmhg"].between(1, 300)
    ]
    return result[["stay_id", "charttime", "map_mmhg"]].sort_values(
        ["stay_id", "charttime"]
    ).reset_index(drop=True)


def normalize_vasoactive_intervals(events: pd.DataFrame) -> pd.DataFrame:
    """Normalize vasoactive infusion rates expressed in µg/kg/min.

    Amount and total quantity fields are intentionally ignored: they are not
    interchangeable with an infusion rate. Rows with other units, absent rates,
    or non-positive/invalid intervals are discarded.
    """
    _require(
        events,
        {"stay_id", "starttime", "endtime", "itemid", "rate", "rateuom"},
        "events",
    )
    result = events.loc[events["itemid"].isin(VASOACTIVE_ITEMS)].copy()
    result["starttime"] = pd.to_datetime(result["starttime"], errors="coerce")
    result["endtime"] = pd.to_datetime(result["endtime"], errors="coerce")
    result["drug"] = result["itemid"].map(VASOACTIVE_ITEMS)
    result["dose_mcg_kg_min"] = pd.to_numeric(result["rate"], errors="coerce")
    unit = (
        result["rateuom"].fillna("").astype(str).str.lower()
        .str.replace("µ", "u", regex=False)
        .str.replace("μ", "u", regex=False)
        .str.replace(r"\s+", "", regex=True)
    )
    accepted_unit = unit.isin(
        {"mcg/kg/min", "ug/kg/min", "mcg/kg/minute", "ug/kg/minute"}
    )
    result = result.loc[
        accepted_unit
        & result["starttime"].notna()
        & result["endtime"].gt(result["starttime"])
        & result["dose_mcg_kg_min"].gt(0)
    ].copy()
    return result[
        ["stay_id", "starttime", "endtime", "drug", "dose_mcg_kg_min"]
    ].sort_values(["stay_id", "starttime", "drug"]).reset_index(drop=True)
