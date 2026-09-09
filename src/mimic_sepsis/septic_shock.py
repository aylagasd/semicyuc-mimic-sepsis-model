"""Auditable primitives for the retrospective septic-shock proxy."""

from __future__ import annotations

import pandas as pd


LACTATE_ITEMIDS = {50813}
VASOPRESSOR_ITEMS = {
    221906: "norepinephrine", 221289: "epinephrine", 221662: "dopamine",
    221749: "phenylephrine", 222315: "vasopressin",
}


def _require(frame: pd.DataFrame, columns: set[str], name: str) -> None:
    missing = sorted(columns - set(frame.columns))
    if missing:
        raise ValueError(f"{name} is missing columns: {', '.join(missing)}")


def normalize_lactate(events: pd.DataFrame) -> pd.DataFrame:
    """Normalize serum/blood lactate to mmol/L and retain availability time."""
    _require(events, {"subject_id", "hadm_id", "itemid", "charttime", "valuenum", "valueuom"}, "events")
    result = events.loc[events["itemid"].isin(LACTATE_ITEMIDS)].copy()
    result["lactate_time"] = pd.to_datetime(
        result["charttime"], errors="coerce", format="mixed"
    )
    if "storetime" in result:
        stored = pd.to_datetime(result["storetime"], errors="coerce", format="mixed")
        result["lactate_available_at"] = stored.where(stored.ge(result["lactate_time"]), result["lactate_time"])
    else:
        result["lactate_available_at"] = result["lactate_time"]
    value = pd.to_numeric(result["valuenum"], errors="coerce")
    unit = result["valueuom"].fillna("").astype(str).str.lower().str.replace(" ", "")
    mmol = unit.isin({"mmol/l", "mmol/liter"})
    mgdl = unit.isin({"mg/dl", "mgdl"})
    result["lactate_mmol_l"] = pd.Series(float("nan"), index=result.index)
    result.loc[mmol, "lactate_mmol_l"] = value.loc[mmol]
    result.loc[mgdl, "lactate_mmol_l"] = value.loc[mgdl] / 9.008
    result = result.loc[
        result["lactate_time"].notna()
        & result["lactate_mmol_l"].gt(0)
        & result["lactate_mmol_l"].le(30)
    ]
    return result[["subject_id", "hadm_id", "lactate_time", "lactate_available_at", "lactate_mmol_l"]].sort_values(
        ["subject_id", "hadm_id", "lactate_time"]
    ).reset_index(drop=True)


def normalize_vasopressor_intervals(events: pd.DataFrame) -> pd.DataFrame:
    """Return valid administration intervals for five Sepsis-3 vasopressors."""
    _require(events, {"stay_id", "itemid", "starttime", "endtime"}, "events")
    result = events.loc[events["itemid"].isin(VASOPRESSOR_ITEMS)].copy()
    result["starttime"] = pd.to_datetime(result["starttime"], errors="coerce")
    result["endtime"] = pd.to_datetime(result["endtime"], errors="coerce")
    result["vasopressor"] = result["itemid"].map(VASOPRESSOR_ITEMS)
    result = result.loc[result["starttime"].notna() & result["endtime"].gt(result["starttime"])]
    return result[["stay_id", "starttime", "endtime", "vasopressor"]].sort_values(
        ["stay_id", "starttime", "vasopressor"]
    ).reset_index(drop=True)


def build_septic_shock_labels(
    sepsis_stays: pd.DataFrame,
    lactates: pd.DataFrame,
    vasopressors: pd.DataFrame,
    *,
    lactate_threshold: float = 2.0,
    concurrency_hours: float = 6,
    association_hours: float = 24,
) -> pd.DataFrame:
    """Label shock when hyperlactatemia and vasopressor therapy co-occur near t0.

    This is an explicit EHR proxy: adequate volume resuscitation is not inferred.
    The earliest qualifying combination is selected deterministically.
    """
    _require(sepsis_stays, {"subject_id", "hadm_id", "stay_id", "t0"}, "sepsis_stays")
    _require(lactates, {"subject_id", "hadm_id", "lactate_time", "lactate_available_at", "lactate_mmol_l"}, "lactates")
    _require(vasopressors, {"stay_id", "starttime", "endtime", "vasopressor"}, "vasopressors")
    if lactate_threshold < 0 or concurrency_hours < 0 or association_hours < 0:
        raise ValueError("Shock thresholds and windows must be non-negative")
    rows = []
    for sepsis in sepsis_stays.itertuples(index=False):
        t0 = pd.to_datetime(sepsis.t0)
        lower, upper = t0 - pd.Timedelta(hours=association_hours), t0 + pd.Timedelta(hours=association_hours)
        labs = lactates.loc[
            lactates["subject_id"].eq(sepsis.subject_id)
            & lactates["hadm_id"].eq(sepsis.hadm_id)
            & lactates["lactate_mmol_l"].gt(lactate_threshold)
            & pd.to_datetime(lactates["lactate_time"]).between(lower, upper, inclusive="both")
        ]
        vaso = vasopressors.loc[
            vasopressors["stay_id"].eq(sepsis.stay_id)
            & pd.to_datetime(vasopressors["starttime"]).le(upper)
            & pd.to_datetime(vasopressors["endtime"]).ge(lower)
        ]
        candidates = []
        tolerance = pd.Timedelta(hours=concurrency_hours)
        for lab in labs.itertuples(index=False):
            for infusion in vaso.itertuples(index=False):
                if lab.lactate_time < infusion.starttime - tolerance or lab.lactate_time > infusion.endtime + tolerance:
                    continue
                onset = max(lab.lactate_time, infusion.starttime)
                available = max(onset, lab.lactate_available_at)
                candidates.append((onset, lab.lactate_time, infusion.starttime, lab, infusion, available))
        candidates.sort(key=lambda item: item[:3])
        if candidates:
            onset, _, _, lab, infusion, available = candidates[0]
            rows.append({
                "subject_id": sepsis.subject_id, "hadm_id": sepsis.hadm_id, "stay_id": sepsis.stay_id,
                "sepsis_t0": t0, "septic_shock": True, "shock_t0": onset,
                "shock_label_available_at": available, "lactate_time": lab.lactate_time,
                "lactate_mmol_l": lab.lactate_mmol_l, "vasopressor": infusion.vasopressor,
                "vasopressor_start": infusion.starttime, "adequate_fluids_verified": False,
            })
        else:
            rows.append({
                "subject_id": sepsis.subject_id, "hadm_id": sepsis.hadm_id, "stay_id": sepsis.stay_id,
                "sepsis_t0": t0, "septic_shock": False, "shock_t0": pd.NaT,
                "shock_label_available_at": pd.NaT, "lactate_time": pd.NaT,
                "lactate_mmol_l": pd.NA, "vasopressor": pd.NA,
                "vasopressor_start": pd.NaT, "adequate_fluids_verified": False,
            })
    return pd.DataFrame(rows)
