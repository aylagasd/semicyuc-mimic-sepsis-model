"""Pure extraction helpers for the respiratory and renal SOFA inputs.

All time windows are half-open (``start <= time < end``), except a rolling
lookback where the landmark itself is included.  This convention prevents an
event from being counted twice in adjacent windows.
"""

from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd


PAO2_ITEMID = 50821
FIO2_ITEMID = 223835
INVASIVE_VENTILATION_ITEMID = 225792
URINE_OUTPUT_ITEMIDS = frozenset({226559, 226560, 226627, 226631})


def _duration(value: timedelta | str) -> timedelta:
    """Parse the deliberately small duration API without NumPy generic units."""
    if isinstance(value, timedelta):
        return value
    text = value.strip().lower()
    if text.endswith("h"):
        return timedelta(hours=float(text[:-1]))
    raise ValueError("Duration strings must use hours, for example '24h'")


def normalize_fio2(value: float | int | None) -> float | None:
    """Return FiO2 as a fraction, accepting either 0.21--1 or 21--100 percent."""
    if value is None or pd.isna(value):
        return None
    value = float(value)
    if 0.21 <= value <= 1:
        return value
    if 21 <= value <= 100:
        return value / 100
    raise ValueError("FiO2 must be in the range 0.21-1 or 21-100 percent")


def pair_pao2_with_fio2(
    pao2_events: pd.DataFrame,
    fio2_events: pd.DataFrame,
    *,
    max_lookback: timedelta | str = "4h",
) -> pd.DataFrame:
    """Pair each PaO2 with the latest preceding FiO2 from the same ICU stay.

    A future FiO2 is never used, even if it is temporally closer. Duplicate
    source rows are removed before matching.
    """
    required = {"stay_id", "itemid", "charttime", "valuenum"}
    for name, frame in (("pao2_events", pao2_events), ("fio2_events", fio2_events)):
        missing = required.difference(frame.columns)
        if missing:
            raise ValueError(f"{name} missing columns: {sorted(missing)}")

    pao2 = pao2_events.loc[pao2_events["itemid"].eq(PAO2_ITEMID), list(required)].copy()
    fio2 = fio2_events.loc[fio2_events["itemid"].eq(FIO2_ITEMID), list(required)].copy()
    pao2["charttime"] = pd.to_datetime(pao2["charttime"])
    fio2["charttime"] = pd.to_datetime(fio2["charttime"])
    pao2 = pao2.drop_duplicates().rename(
        columns={"charttime": "pao2_time", "valuenum": "pao2"}
    )
    fio2 = fio2.drop_duplicates().rename(
        columns={"charttime": "fio2_time", "valuenum": "fio2_raw"}
    )
    def safe_fio2(value: object) -> float | None:
        try:
            return normalize_fio2(value)
        except (TypeError, ValueError):
            return None

    fio2["fio2"] = fio2["fio2_raw"].map(safe_fio2)
    fio2 = fio2.dropna(subset=["fio2"])
    pao2 = pao2.loc[pao2["pao2"].gt(0)]

    chunks: list[pd.DataFrame] = []
    tolerance = _duration(max_lookback)
    for stay_id, stay_pao2 in pao2.groupby("stay_id", sort=False):
        stay_fio2 = fio2.loc[fio2["stay_id"].eq(stay_id)]
        matched = pd.merge_asof(
            stay_pao2.sort_values("pao2_time"),
            stay_fio2[["fio2_time", "fio2"]].sort_values("fio2_time"),
            left_on="pao2_time",
            right_on="fio2_time",
            direction="backward",
            tolerance=tolerance,
        )
        chunks.append(matched)
    columns = ["stay_id", "pao2_time", "pao2", "fio2_time", "fio2"]
    if not chunks:
        return pd.DataFrame(columns=columns + ["pao2_fio2"])
    result = pd.concat(chunks, ignore_index=True)[columns]
    result["pao2_fio2"] = result["pao2"] / result["fio2"]
    return result


def add_contemporaneous_invasive_ventilation(
    respiratory: pd.DataFrame, procedures: pd.DataFrame
) -> pd.DataFrame:
    """Flag PaO2 observations occurring inside an invasive ventilation interval."""
    required_resp = {"stay_id", "pao2_time"}
    required_proc = {"stay_id", "itemid", "starttime", "endtime"}
    if missing := required_resp.difference(respiratory.columns):
        raise ValueError(f"respiratory missing columns: {sorted(missing)}")
    if missing := required_proc.difference(procedures.columns):
        raise ValueError(f"procedures missing columns: {sorted(missing)}")

    result = respiratory.copy()
    result["pao2_time"] = pd.to_datetime(result["pao2_time"])
    procedures = procedures.loc[
        procedures["itemid"].eq(INVASIVE_VENTILATION_ITEMID)
    ].copy()
    procedures["starttime"] = pd.to_datetime(procedures["starttime"])
    procedures["endtime"] = pd.to_datetime(procedures["endtime"])
    procedures = procedures.dropna(subset=["starttime", "endtime"])
    procedures = procedures.loc[procedures["endtime"].gt(procedures["starttime"])]

    flags = []
    for row in result[["stay_id", "pao2_time"]].itertuples(index=False):
        intervals = procedures.loc[procedures["stay_id"].eq(row.stay_id)]
        flags.append(
            bool(
                (
                    intervals["starttime"].le(row.pao2_time)
                    & intervals["endtime"].gt(row.pao2_time)
                ).any()
            )
        )
    result["invasive_ventilation"] = flags
    return result


def urine_output_at_landmarks(
    urine_events: pd.DataFrame,
    landmarks: pd.DataFrame,
    *,
    lookback: timedelta | str = "24h",
) -> pd.DataFrame:
    """Sum validated urine output in ``(landmark-lookback, landmark]``.

    Exact duplicate source events are counted once; negative volumes and
    non-urine itemids are excluded. Events after a landmark cannot contribute.
    """
    required_events = {"stay_id", "itemid", "charttime", "value"}
    required_landmarks = {"stay_id", "landmark_time"}
    if missing := required_events.difference(urine_events.columns):
        raise ValueError(f"urine_events missing columns: {sorted(missing)}")
    if missing := required_landmarks.difference(landmarks.columns):
        raise ValueError(f"landmarks missing columns: {sorted(missing)}")

    events = urine_events.loc[
        urine_events["itemid"].isin(URINE_OUTPUT_ITEMIDS), list(required_events)
    ].copy()
    events["charttime"] = pd.to_datetime(events["charttime"])
    events["value"] = pd.to_numeric(events["value"], errors="coerce")
    events = events.dropna(subset=["charttime", "value"]).drop_duplicates()
    events = events.loc[events["value"].ge(0)]

    result = landmarks.copy()
    result["landmark_time"] = pd.to_datetime(result["landmark_time"])
    delta = _duration(lookback)
    result["_row_order"] = np.arange(len(result))
    chunks = []
    event_groups = {key: group.sort_values("charttime") for key, group in events.groupby("stay_id")}
    for stay_id, stay_landmarks in result.groupby("stay_id", sort=False):
        chunk = stay_landmarks.copy()
        stay_events = event_groups.get(stay_id)
        if stay_events is None or stay_events.empty:
            chunk["urine_output_ml"] = np.nan
        else:
            times = stay_events["charttime"].to_numpy(dtype="datetime64[ns]")
            values = stay_events["value"].to_numpy(dtype=float)
            prefix = np.concatenate(([0.0], np.cumsum(values)))
            landmarks_ns = chunk["landmark_time"].to_numpy(dtype="datetime64[ns]")
            starts = np.searchsorted(times, landmarks_ns - np.timedelta64(int(delta.total_seconds()), "s"), side="right")
            ends = np.searchsorted(times, landmarks_ns, side="right")
            totals = prefix[ends] - prefix[starts]
            totals[ends == starts] = np.nan
            chunk["urine_output_ml"] = totals
        chunks.append(chunk)
    result = pd.concat(chunks).sort_values("_row_order").drop(columns="_row_order")
    return result
