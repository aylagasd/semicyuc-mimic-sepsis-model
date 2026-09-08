"""Hourly SOFA grid and leakage-safe rolling aggregation utilities."""

from __future__ import annotations

import math
from datetime import timedelta

import numpy as np
import pandas as pd


HEART_RATE_ITEMID = 220045


def build_icustay_hourly_grid(
    icustays: pd.DataFrame,
    chartevents: pd.DataFrame,
    *,
    pre_hours: int = 24,
) -> pd.DataFrame:
    """Reproduce the v2.4.0 clock-hour grid based on heart-rate coverage.

    The grid runs from 24 hours before the ceiling of the first heart-rate
    measurement through the ceiling of the last-minus-first duration.
    Stays without a heart-rate measurement are retained in an audit table by
    callers but cannot produce an official-compatible hourly grid.
    """
    required_stays = {"subject_id", "hadm_id", "stay_id"}
    required_chart = {"stay_id", "itemid", "charttime"}
    for frame, required, name in [
        (icustays, required_stays, "icustays"),
        (chartevents, required_chart, "chartevents"),
    ]:
        missing = sorted(required - set(frame.columns))
        if missing:
            raise ValueError(f"{name} is missing columns: {', '.join(missing)}")
    if pre_hours < 0:
        raise ValueError("pre_hours must be non-negative")
    heart_rate = chartevents.loc[chartevents["itemid"].eq(HEART_RATE_ITEMID), ["stay_id", "charttime"]].copy()
    heart_rate["charttime"] = pd.to_datetime(heart_rate["charttime"], errors="coerce")
    times = heart_rate.dropna(subset=["charttime"]).groupby("stay_id")["charttime"].agg(
        intime_hr="min", outtime_hr="max"
    ).reset_index()
    source = icustays[list(required_stays)].merge(times, on="stay_id", how="inner", validate="one_to_one")
    rows: list[dict[str, object]] = []
    for stay in source.itertuples(index=False):
        first_endtime = stay.intime_hr.ceil("h")
        duration_hours = math.ceil((stay.outtime_hr - stay.intime_hr).total_seconds() / 3600)
        for hour in range(-pre_hours, duration_hours + 1):
            rows.append({
                "subject_id": stay.subject_id,
                "hadm_id": stay.hadm_id,
                "stay_id": stay.stay_id,
                "hr": hour,
                "endtime": first_endtime + timedelta(hours=hour),
            })
    return pd.DataFrame(rows, columns=["subject_id", "hadm_id", "stay_id", "hr", "endtime"])


def rolling_worst_score(
    grid: pd.DataFrame,
    scored_events: pd.DataFrame,
    *,
    window_hours: int = 24,
) -> pd.DataFrame:
    """Attach maximum event score in ``(endtime-window, endtime]`` per stay."""
    required_grid = {"stay_id", "hr", "endtime"}
    required_events = {"stay_id", "event_time", "score"}
    for frame, required, name in [
        (grid, required_grid, "grid"), (scored_events, required_events, "scored_events")
    ]:
        missing = sorted(required - set(frame.columns))
        if missing:
            raise ValueError(f"{name} is missing columns: {', '.join(missing)}")
    if window_hours <= 0:
        raise ValueError("window_hours must be positive")
    result = grid.copy()
    result["endtime"] = pd.to_datetime(result["endtime"], errors="raise")
    events = scored_events.copy()
    events["event_time"] = pd.to_datetime(events["event_time"], errors="coerce")
    events = events.dropna(subset=["event_time", "score"])
    delta = timedelta(hours=window_hours)
    result["_row_order"] = np.arange(len(result))
    chunks = []
    groups = {key: group.sort_values("event_time") for key, group in events.groupby("stay_id")}
    for stay_id, stay_grid in result.groupby("stay_id", sort=False):
        chunk = stay_grid.copy()
        stay_events = groups.get(stay_id)
        if stay_events is None or stay_events.empty:
            chunk["score_24h"] = pd.array([None] * len(chunk), dtype="Int64")
        else:
            times = stay_events["event_time"].to_numpy(dtype="datetime64[ns]")
            scores = stay_events["score"].to_numpy(dtype=int)
            ends_at = chunk["endtime"].to_numpy(dtype="datetime64[ns]")
            starts = np.searchsorted(times, ends_at - np.timedelta64(int(delta.total_seconds()), "s"), side="right")
            ends = np.searchsorted(times, ends_at, side="right")
            values = [None if start == end else int(scores[start:end].max()) for start, end in zip(starts, ends)]
            chunk["score_24h"] = pd.array(values, dtype="Int64")
        chunks.append(chunk)
    return pd.concat(chunks).sort_values("_row_order").drop(columns="_row_order")
