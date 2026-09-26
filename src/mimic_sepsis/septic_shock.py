"""Auditable primitives for the retrospective septic-shock proxy."""

from __future__ import annotations

from datetime import timedelta
from typing import Iterable

import pandas as pd


LACTATE_ITEMIDS = {50813}
VASOPRESSOR_ITEMS = {
    221906: "norepinephrine", 221289: "epinephrine", 221662: "dopamine",
    221749: "phenylephrine", 222315: "vasopressin",
}
SHOCK_COLUMNS = [
    "subject_id", "hadm_id", "stay_id", "sepsis_t0", "septic_shock",
    "shock_t0", "shock_label_available_at", "lactate_time",
    "lactate_mmol_l", "vasopressor", "vasopressor_start",
    "adequate_fluids_verified",
]
SHOCK_SENSITIVITY_COLUMNS = ["sensitivity", "concurrency_hours", *SHOCK_COLUMNS]


def _require(frame: pd.DataFrame, columns: set[str], name: str) -> None:
    missing = sorted(columns - set(frame.columns))
    if missing:
        raise ValueError(f"{name} is missing columns: {', '.join(missing)}")


def normalize_lactate(
    events: pd.DataFrame,
    allowed_itemids: Iterable[int] | None = None,
) -> pd.DataFrame:
    """Normalize serum/blood lactate to mmol/L and retain availability time."""
    _require(events, {"subject_id", "hadm_id", "itemid", "charttime", "valuenum", "valueuom"}, "events")
    itemids = LACTATE_ITEMIDS if allowed_itemids is None else {
        int(itemid) for itemid in allowed_itemids
    }
    unknown = sorted(itemids - LACTATE_ITEMIDS)
    if unknown:
        raise ValueError(
            "Unknown lactate itemids: " + ", ".join(map(str, unknown))
        )
    result = events.loc[events["itemid"].isin(itemids)].copy()
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


def normalize_vasopressor_intervals(
    events: pd.DataFrame,
    allowed_vasopressors: Iterable[str] | None = None,
) -> pd.DataFrame:
    """Return valid administration intervals for configured vasopressors."""
    _require(events, {"stay_id", "itemid", "starttime", "endtime"}, "events")
    known = set(VASOPRESSOR_ITEMS.values())
    allowed = known if allowed_vasopressors is None else {
        str(name).strip().lower() for name in allowed_vasopressors
    }
    unknown = sorted(allowed - known)
    if unknown:
        raise ValueError("Unknown vasopressors: " + ", ".join(unknown))
    itemids = {
        itemid for itemid, name in VASOPRESSOR_ITEMS.items() if name in allowed
    }
    result = events.loc[events["itemid"].isin(itemids)].copy()
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
    association_hours_before: float = 24,
    association_hours_after: float = 24,
) -> pd.DataFrame:
    """Label shock when hyperlactatemia and vasopressor therapy co-occur near t0.

    This is an explicit EHR proxy: adequate volume resuscitation is not inferred.
    The earliest qualifying combination is selected deterministically.
    """
    _require(sepsis_stays, {"subject_id", "hadm_id", "stay_id", "t0"}, "sepsis_stays")
    _require(lactates, {"subject_id", "hadm_id", "lactate_time", "lactate_available_at", "lactate_mmol_l"}, "lactates")
    _require(vasopressors, {"stay_id", "starttime", "endtime", "vasopressor"}, "vasopressors")
    if (
        lactate_threshold < 0
        or concurrency_hours < 0
        or association_hours_before < 0
        or association_hours_after < 0
    ):
        raise ValueError("Shock thresholds and windows must be non-negative")
    # Index once by admission/stay. Repeated full-frame boolean scans make the
    # full MIMIC-IV run quadratic in the number of septic stays.
    lactates = lactates.copy()
    lactates["lactate_time"] = pd.to_datetime(lactates["lactate_time"])
    lactates["lactate_available_at"] = pd.to_datetime(
        lactates["lactate_available_at"]
    )
    vasopressors = vasopressors.copy()
    vasopressors["starttime"] = pd.to_datetime(vasopressors["starttime"])
    vasopressors["endtime"] = pd.to_datetime(vasopressors["endtime"])
    lactate_indices = lactates.groupby(
        ["subject_id", "hadm_id"], sort=False
    ).indices
    vasopressor_indices = vasopressors.groupby("stay_id", sort=False).indices
    rows = []
    for sepsis in sepsis_stays.itertuples(index=False):
        t0 = pd.to_datetime(sepsis.t0)
        lower = t0 - timedelta(hours=association_hours_before)
        upper = t0 + timedelta(hours=association_hours_after)
        lab_rows = lactate_indices.get((sepsis.subject_id, sepsis.hadm_id))
        vaso_rows = vasopressor_indices.get(sepsis.stay_id)
        admission_labs = (
            lactates.iloc[lab_rows] if lab_rows is not None else lactates.iloc[0:0]
        )
        stay_vasopressors = (
            vasopressors.iloc[vaso_rows]
            if vaso_rows is not None
            else vasopressors.iloc[0:0]
        )
        labs = admission_labs.loc[
            admission_labs["lactate_mmol_l"].gt(lactate_threshold)
            & admission_labs["lactate_time"].between(lower, upper, inclusive="both")
        ]
        vaso = stay_vasopressors.loc[
            stay_vasopressors["starttime"].le(upper)
            & stay_vasopressors["endtime"].ge(lower)
        ]
        candidates = []
        tolerance = timedelta(hours=concurrency_hours)
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
    return pd.DataFrame(rows, columns=SHOCK_COLUMNS)


def build_concurrency_sensitivity_labels(
    sepsis_stays: pd.DataFrame,
    lactates: pd.DataFrame,
    vasopressors: pd.DataFrame,
    *,
    concurrency_hours: Iterable[float],
    lactate_threshold: float = 2.0,
    association_hours_before: float = 24,
    association_hours_after: float = 24,
) -> pd.DataFrame:
    """Recompute long-format shock labels for prespecified concurrency windows."""
    windows = [float(hours) for hours in concurrency_hours]
    if not windows or len(set(windows)) != len(windows) or any(
        hours < 0 for hours in windows
    ):
        raise ValueError("Sensitivity concurrency windows must be unique and non-negative")
    frames = []
    for hours in windows:
        labels = build_septic_shock_labels(
            sepsis_stays,
            lactates,
            vasopressors,
            lactate_threshold=lactate_threshold,
            concurrency_hours=hours,
            association_hours_before=association_hours_before,
            association_hours_after=association_hours_after,
        )
        # Stabilize nullable dtypes across variants that may have no positives;
        # this prevents concat from inferring a different schema from prevalence.
        labels["lactate_mmol_l"] = pd.to_numeric(
            labels["lactate_mmol_l"], errors="coerce"
        ).astype("Float64")
        labels["vasopressor"] = labels["vasopressor"].astype("string")
        labels.insert(0, "concurrency_hours", hours)
        labels.insert(0, "sensitivity", f"concurrency_{hours:g}h")
        frames.append(labels)
    return pd.concat(frames, ignore_index=True)[SHOCK_SENSITIVITY_COLUMNS]
