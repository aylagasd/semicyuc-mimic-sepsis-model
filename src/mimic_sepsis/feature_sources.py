"""Normalize an initial, auditable set of real-time predictor events."""

from __future__ import annotations

from collections.abc import Mapping

import pandas as pd


# Item identifiers are deliberately explicit and version-controlled. Values
# outside broad physiological bounds are rejected rather than winsorized here.
VITAL_ITEMS: Mapping[int, tuple[str, float, float]] = {
    220045: ("heart_rate", 1, 350),
    220052: ("map", 1, 300),
    220210: ("resp_rate", 1, 100),
    220277: ("spo2", 1, 100),
    223761: ("temperature_f", 50, 120),
    223762: ("temperature", 10, 50),
}

LAB_ITEMS: Mapping[int, tuple[str, float, float]] = {
    51300: ("wbc", 0, 1000),
    51301: ("wbc", 0, 1000),
    50912: ("creatinine", 0, 100),
    52546: ("creatinine", 0, 100),
    50885: ("bilirubin", 0, 100),
    53089: ("bilirubin", 0, 100),
    51265: ("platelets", 0, 5000),
    50813: ("lactate", 0, 50),
}


def _require(frame: pd.DataFrame, columns: set[str], name: str) -> None:
    missing = sorted(columns - set(frame.columns))
    if missing:
        raise ValueError(f"{name} is missing columns: {', '.join(missing)}")


def normalize_vital_events(chartevents: pd.DataFrame) -> pd.DataFrame:
    """Return valid bedside measurements with their charted availability time."""
    _require(chartevents, {"stay_id", "itemid", "charttime", "valuenum"}, "chartevents")
    source = chartevents.loc[chartevents["itemid"].isin(VITAL_ITEMS)].copy()
    source["event_time"] = pd.to_datetime(
        source["charttime"], errors="coerce", format="mixed"
    )
    source["value"] = pd.to_numeric(source["valuenum"], errors="coerce")
    source["variable"] = source["itemid"].map(lambda item: VITAL_ITEMS[int(item)][0])
    fahrenheit = source["variable"].eq("temperature_f")
    source.loc[fahrenheit, "value"] = (source.loc[fahrenheit, "value"] - 32) * 5 / 9
    source.loc[fahrenheit, "variable"] = "temperature"
    valid = pd.Series(False, index=source.index)
    for itemid, (_, low, high) in VITAL_ITEMS.items():
        bounds = ((low - 32) * 5 / 9, (high - 32) * 5 / 9) if itemid == 223761 else (low, high)
        valid |= source["itemid"].eq(itemid) & source["value"].between(*bounds)
    return (
        source.loc[valid & source["event_time"].notna(), [
            "stay_id", "event_time", "variable", "value", "itemid"
        ]]
        .sort_values(["stay_id", "event_time", "variable", "itemid"])
        .reset_index(drop=True)
    )


def normalize_lab_feature_events(
    labevents: pd.DataFrame, icustays: pd.DataFrame
) -> pd.DataFrame:
    """Link labs by specimen time but expose them only at ``storetime``.

    A laboratory value is attributed to the ICU stay containing its specimen
    ``charttime``. Its predictor ``event_time`` is the later database
    ``storetime``; absent store times are excluded rather than backdated.
    """
    _require(
        labevents,
        {"subject_id", "hadm_id", "itemid", "charttime", "storetime", "valuenum"},
        "labevents",
    )
    _require(
        icustays,
        {"subject_id", "hadm_id", "stay_id", "intime", "outtime"},
        "icustays",
    )
    labs = labevents.loc[labevents["itemid"].isin(LAB_ITEMS)].copy()
    labs["specimen_time"] = pd.to_datetime(labs["charttime"], errors="coerce", format="mixed")
    labs["event_time"] = pd.to_datetime(labs["storetime"], errors="coerce", format="mixed")
    labs["value"] = pd.to_numeric(labs["valuenum"], errors="coerce")
    labs["variable"] = labs["itemid"].map(lambda item: LAB_ITEMS[int(item)][0])
    valid = pd.Series(False, index=labs.index)
    for itemid, (_, low, high) in LAB_ITEMS.items():
        valid |= labs["itemid"].eq(itemid) & labs["value"].between(low, high)
    labs = labs.loc[
        valid & labs["specimen_time"].notna() & labs["event_time"].notna()
    ].copy()
    stays = icustays[["subject_id", "hadm_id", "stay_id", "intime", "outtime"]].copy()
    stays["intime"] = pd.to_datetime(stays["intime"], errors="coerce", format="mixed")
    stays["outtime"] = pd.to_datetime(stays["outtime"], errors="coerce", format="mixed")
    linked = labs.merge(stays, on=["subject_id", "hadm_id"], how="inner")
    linked = linked.loc[
        linked["specimen_time"].ge(linked["intime"])
        & linked["specimen_time"].lt(linked["outtime"])
    ].copy()
    return (
        linked[["stay_id", "event_time", "specimen_time", "variable", "value", "itemid"]]
        .sort_values(["stay_id", "event_time", "variable", "itemid"])
        .reset_index(drop=True)
    )
