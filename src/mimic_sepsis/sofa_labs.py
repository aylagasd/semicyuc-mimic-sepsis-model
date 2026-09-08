"""Normalize and reduce MIMIC-IV laboratory inputs used by SOFA.

The module targets MIMIC-IV v2.2 ``hosp.labevents``.  It deliberately keeps
laboratory extraction separate from component scoring: the output values use
the canonical units expected by :mod:`mimic_sepsis.sofa`.
"""

from __future__ import annotations

from collections.abc import Mapping

import pandas as pd


LAB_COMPONENTS: Mapping[int, tuple[str, str]] = {
    51265: ("platelets", "10^9/L"),
    50885: ("bilirubin", "mg/dL"),
    53089: ("bilirubin", "mg/dL"),
    50912: ("creatinine", "mg/dL"),
    52546: ("creatinine", "mg/dL"),
}

NORMALIZED_COLUMNS = [
    "lab_event_id",
    "subject_id",
    "hadm_id",
    "charttime",
    "itemid",
    "component",
    "value",
    "unit",
]


def _require_columns(frame: pd.DataFrame, name: str, columns: set[str]) -> None:
    missing = sorted(columns - set(frame.columns))
    if missing:
        raise ValueError(f"{name} is missing columns: {', '.join(missing)}")


def _compact_unit(value: object) -> str:
    return (
        str(value)
        .strip()
        .lower()
        .replace(" ", "")
        .replace("µ", "u")
        .replace("μ", "u")
        .replace("³", "3")
    )


def normalize_sofa_labs(labevents: pd.DataFrame) -> pd.DataFrame:
    """Select SOFA laboratory itemids and convert them to canonical units.

    Platelets are returned in ``10^9/L`` and bilirubin/creatinine in
    ``mg/dL``. Rows with missing identifiers, time or numeric value are
    excluded. Unsupported units raise an error rather than being combined
    silently. Times are parsed as UTC and then made timezone-naive, matching
    the timezone-free timestamps distributed in MIMIC-IV.
    """
    _require_columns(
        labevents,
        "labevents",
        {"subject_id", "hadm_id", "itemid", "charttime", "valuenum", "valueuom"},
    )
    if labevents.empty:
        return pd.DataFrame(columns=NORMALIZED_COLUMNS)

    labs = labevents.loc[labevents["itemid"].isin(LAB_COMPONENTS)].copy()
    if labs.empty:
        return pd.DataFrame(columns=NORMALIZED_COLUMNS)
    labs["lab_event_id"] = labs.index
    labs["charttime"] = pd.to_datetime(
        labs["charttime"], errors="coerce", utc=True, format="mixed"
    ).dt.tz_localize(None)
    labs["value"] = pd.to_numeric(labs["valuenum"], errors="coerce")
    labs = labs.dropna(
        subset=["subject_id", "hadm_id", "charttime", "itemid", "value", "valueuom"]
    )
    labs = labs.loc[labs["value"] >= 0].copy()
    labs["component"] = labs["itemid"].map(lambda item: LAB_COMPONENTS[int(item)][0])
    units = labs["valueuom"].map(_compact_unit)

    platelet_units = {"k/ul", "k/uL".lower(), "10^3/ul", "10^9/l"}
    mass_units = {"mg/dl"}
    molar_units = {"umol/l", "micromol/l"}
    platelet = labs["component"].eq("platelets")
    mass = labs["component"].isin(["bilirubin", "creatinine"])
    supported = (
        (platelet & units.isin(platelet_units))
        | (mass & units.isin(mass_units | molar_units))
    )
    if not supported.all():
        bad = sorted(
            {
                f"{component}:{unit}"
                for component, unit in zip(
                    labs.loc[~supported, "component"], units.loc[~supported]
                )
            }
        )
        raise ValueError(f"Unsupported SOFA laboratory units: {', '.join(bad)}")

    bilirubin_molar = labs["component"].eq("bilirubin") & units.isin(molar_units)
    creatinine_molar = labs["component"].eq("creatinine") & units.isin(molar_units)
    labs.loc[bilirubin_molar, "value"] /= 17.104
    labs.loc[creatinine_molar, "value"] /= 88.4
    labs["unit"] = labs["itemid"].map(lambda item: LAB_COMPONENTS[int(item)][1])
    return (
        labs[NORMALIZED_COLUMNS]
        .sort_values(["subject_id", "hadm_id", "charttime", "itemid", "lab_event_id"])
        .reset_index(drop=True)
    )


def link_labs_to_icu_stays(
    normalized_labs: pd.DataFrame, icustays: pd.DataFrame
) -> pd.DataFrame:
    """Attach events to the ICU stay containing their chart time.

    The interval is half-open: ``intime <= charttime < outtime``. Matching
    requires both ``subject_id`` and ``hadm_id``. An event matching overlapping
    stays raises because silently duplicating it would bias the worst value.
    """
    _require_columns(
        normalized_labs,
        "normalized_labs",
        set(NORMALIZED_COLUMNS),
    )
    _require_columns(
        icustays,
        "icustays",
        {"subject_id", "hadm_id", "stay_id", "intime", "outtime"},
    )
    output_columns = [*NORMALIZED_COLUMNS, "stay_id", "intime", "outtime"]
    if normalized_labs.empty or icustays.empty:
        return pd.DataFrame(columns=output_columns)

    stays = icustays[
        ["subject_id", "hadm_id", "stay_id", "intime", "outtime"]
    ].copy()
    for column in ["intime", "outtime"]:
        stays[column] = pd.to_datetime(
            stays[column], errors="coerce", utc=True, format="mixed"
        ).dt.tz_localize(None)
    stays = stays.dropna(subset=["subject_id", "hadm_id", "stay_id", "intime", "outtime"])
    stays = stays.loc[stays["outtime"] > stays["intime"]]

    linked = normalized_labs.merge(
        stays,
        on=["subject_id", "hadm_id"],
        how="inner",
        validate="many_to_many",
    )
    linked = linked.loc[
        linked["charttime"].ge(linked["intime"])
        & linked["charttime"].lt(linked["outtime"])
    ].copy()
    if linked.duplicated("lab_event_id", keep=False).any():
        raise ValueError("A laboratory event matches more than one ICU stay")
    return linked[output_columns].sort_values(
        ["stay_id", "charttime", "component", "lab_event_id"]
    ).reset_index(drop=True)


def worst_sofa_labs_in_windows(
    linked_labs: pd.DataFrame, windows: pd.DataFrame
) -> pd.DataFrame:
    """Return worst values in official SOFA windows ``(start, end]``.

    ``windows`` must contain a unique ``window_id``, ``stay_id``,
    ``window_start`` and ``window_end``. The minimum platelet count and maximum
    bilirubin and creatinine are retained. Missing components are represented
    by absent rows, not implicitly normal values.
    """
    _require_columns(
        linked_labs,
        "linked_labs",
        set(NORMALIZED_COLUMNS) | {"stay_id"},
    )
    _require_columns(
        windows,
        "windows",
        {"window_id", "stay_id", "window_start", "window_end"},
    )
    result_columns = [
        "window_id",
        "stay_id",
        "component",
        "worst_value",
        "unit",
        "worst_charttime",
        "lab_event_id",
    ]
    if windows["window_id"].duplicated().any():
        raise ValueError("window_id must be unique")
    periods = windows[["window_id", "stay_id", "window_start", "window_end"]].copy()
    for column in ["window_start", "window_end"]:
        periods[column] = pd.to_datetime(
            periods[column], errors="coerce", utc=True, format="mixed"
        ).dt.tz_localize(None)
    if periods[["window_start", "window_end"]].isna().any(axis=None):
        raise ValueError("Windows must have valid start and end times")
    if periods["window_end"].le(periods["window_start"]).any():
        raise ValueError("window_end must be later than window_start")
    if linked_labs.empty or periods.empty:
        return pd.DataFrame(columns=result_columns)

    candidates = periods.merge(linked_labs, on="stay_id", how="inner")
    candidates = candidates.loc[
        candidates["charttime"].gt(candidates["window_start"])
        & candidates["charttime"].le(candidates["window_end"])
    ].copy()
    if candidates.empty:
        return pd.DataFrame(columns=result_columns)
    candidates["_severity_value"] = candidates["value"]
    candidates.loc[
        candidates["component"].eq("platelets"), "_severity_value"
    ] *= -1
    candidates = candidates.sort_values(
        ["window_id", "component", "_severity_value", "charttime", "lab_event_id"],
        ascending=[True, True, False, True, True],
    )
    worst = candidates.drop_duplicates(["window_id", "component"], keep="first")
    return (
        worst.rename(
            columns={"value": "worst_value", "charttime": "worst_charttime"}
        )[result_columns]
        .sort_values(["window_id", "component"])
        .reset_index(drop=True)
    )
