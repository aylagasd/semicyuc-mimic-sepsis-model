"""Landmark risk sets and future outcomes with explicit temporal boundaries."""

from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd


LANDMARK_COLUMNS = [
    "subject_id", "hadm_id", "stay_id", "landmark_hour", "landmark_time",
    "horizon_hours", "horizon_end", "followup_end", "horizon_observed",
    "outcome", "event_time",
]


def _require(frame: pd.DataFrame, columns: set[str], name: str) -> None:
    missing = sorted(columns - set(frame.columns))
    if missing:
        raise ValueError(f"{name} is missing columns: {', '.join(missing)}")


def build_landmark_outcomes(
    icustays: pd.DataFrame,
    outcomes: pd.DataFrame,
    *,
    event_time_column: str = "t0",
    horizon_hours: int = 6,
    minimum_observation_hours: int = 6,
    landmark_interval_hours: int = 1,
) -> pd.DataFrame:
    """Build an incident risk set using outcome interval ``(L, L + H]``.

    Landmarks at or after onset are absent. If ICU follow-up ends before the
    horizon, an observed event remains positive; otherwise the outcome is
    nullable/censored rather than silently treated as a control.
    """
    _require(
        icustays, {"subject_id", "hadm_id", "stay_id", "intime", "outtime"},
        "icustays",
    )
    _require(outcomes, {"stay_id", event_time_column}, "outcomes")
    if horizon_hours <= 0 or minimum_observation_hours < 0 or landmark_interval_hours <= 0:
        raise ValueError("Horizon/interval must be positive and observation non-negative")
    if icustays["stay_id"].duplicated().any():
        raise ValueError("icustays must be unique by stay_id")
    if outcomes["stay_id"].duplicated().any():
        raise ValueError("outcomes must be unique by stay_id")

    stays = icustays.copy()
    for column in ("intime", "outtime"):
        stays[column] = pd.to_datetime(stays[column], errors="coerce", format="mixed")
    events = outcomes[["stay_id", event_time_column]].copy()
    events[event_time_column] = pd.to_datetime(
        events[event_time_column], errors="coerce", format="mixed"
    )
    stays = stays.merge(events, on="stay_id", how="left", validate="one_to_one")
    rows: list[dict[str, object]] = []
    step = timedelta(hours=landmark_interval_hours)
    horizon = timedelta(hours=horizon_hours)
    start_delta = timedelta(hours=minimum_observation_hours)

    for stay in stays.itertuples(index=False):
        if pd.isna(stay.intime) or pd.isna(stay.outtime) or stay.outtime <= stay.intime:
            continue
        event_time = getattr(stay, event_time_column)
        landmark = stay.intime + start_delta
        landmark_hour = minimum_observation_hours
        while landmark < stay.outtime and (pd.isna(event_time) or landmark < event_time):
            horizon_end = landmark + horizon
            followup_end = min(horizon_end, stay.outtime)
            positive = bool(
                pd.notna(event_time)
                and event_time > landmark
                and event_time <= followup_end
            )
            fully_observed = stay.outtime >= horizon_end
            if positive:
                outcome = 1
            elif fully_observed:
                outcome = 0
            else:
                outcome = pd.NA
            rows.append({
                "subject_id": stay.subject_id,
                "hadm_id": stay.hadm_id,
                "stay_id": stay.stay_id,
                "landmark_hour": landmark_hour,
                "landmark_time": landmark,
                "horizon_hours": horizon_hours,
                "horizon_end": horizon_end,
                "followup_end": followup_end,
                "horizon_observed": fully_observed or positive,
                "outcome": outcome,
                "event_time": event_time,
            })
            landmark += step
            landmark_hour += landmark_interval_hours
    result = pd.DataFrame(rows, columns=LANDMARK_COLUMNS)
    if result.empty:
        return result
    result["outcome"] = pd.array(result["outcome"], dtype="Int8")
    result["horizon_observed"] = result["horizon_observed"].astype(bool)
    result["landmark_hour"] = result["landmark_hour"].astype(np.int32)
    result["horizon_hours"] = result["horizon_hours"].astype(np.int16)
    return result.sort_values(["stay_id", "landmark_time"]).reset_index(drop=True)


def build_multiple_horizons(
    icustays: pd.DataFrame,
    outcomes: pd.DataFrame,
    *,
    horizons_hours: tuple[int, ...] = (3, 6, 12, 24),
    **kwargs,
) -> pd.DataFrame:
    """Stack landmark outcomes for unique, positive prediction horizons."""
    horizons = tuple(dict.fromkeys(horizons_hours))
    if not horizons or any(value <= 0 for value in horizons):
        raise ValueError("horizons_hours must contain positive values")
    frames = [
        build_landmark_outcomes(
            icustays, outcomes, horizon_hours=value, **kwargs
        )
        for value in horizons
    ]
    return pd.concat(frames, ignore_index=True).sort_values(
        ["stay_id", "landmark_time", "horizon_hours"]
    ).reset_index(drop=True)
