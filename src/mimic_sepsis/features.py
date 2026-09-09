"""Leakage-safe numeric feature aggregation before prediction landmarks."""

from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd


KEYS = ["subject_id", "hadm_id", "stay_id", "landmark_time"]


def _require(frame: pd.DataFrame, columns: set[str], name: str) -> None:
    missing = sorted(columns - set(frame.columns))
    if missing:
        raise ValueError(f"{name} is missing columns: {', '.join(missing)}")


def numeric_window_features(
    landmarks: pd.DataFrame,
    events: pd.DataFrame,
    *,
    variable: str,
    lookback_hours: int = 24,
) -> pd.DataFrame:
    """Aggregate numeric events in the left-closed/right-open window ``[L-W,L)``.

    Output retains identifiers solely as join keys. They are not candidate
    predictors. The slope is units per hour and requires two distinct times.
    """
    _require(landmarks, set(KEYS), "landmarks")
    _require(events, {"stay_id", "event_time", "value"}, "events")
    if not variable or not variable.replace("_", "").isalnum():
        raise ValueError("variable must be a non-empty alphanumeric snake-case name")
    if lookback_hours <= 0:
        raise ValueError("lookback_hours must be positive")
    if landmarks.duplicated(["stay_id", "landmark_time"]).any():
        raise ValueError("landmarks must be unique by stay_id and landmark_time")

    points = landmarks[KEYS].copy()
    points["landmark_time"] = pd.to_datetime(
        points["landmark_time"], errors="raise", format="mixed"
    )
    suffix = f"{lookback_hours}h"
    feature_columns = [
        f"{variable}_{stat}_{suffix}"
        for stat in (
            "count", "missing", "last", "min", "max", "mean", "std", "slope",
            "hours_since_last",
        )
    ]
    if points.empty:
        return points.assign(**{column: pd.Series(dtype="float64") for column in feature_columns})
    source = events[["stay_id", "event_time", "value"]].copy()
    source["event_time"] = pd.to_datetime(
        source["event_time"], errors="coerce", format="mixed"
    )
    source["value"] = pd.to_numeric(source["value"], errors="coerce")
    source = source.dropna(subset=["stay_id", "event_time", "value"])
    grouped = {}
    for stay_id, part in source.groupby("stay_id"):
        part = part.sort_values("event_time")
        times = part["event_time"].to_numpy(dtype="datetime64[ns]")
        values = part["value"].to_numpy(dtype=float)
        x = (times - times[0]) / np.timedelta64(1, "h")
        grouped[stay_id] = {
            "times": times,
            "values": values,
            "sum": np.r_[0.0, np.cumsum(values)],
            "sumsq": np.r_[0.0, np.cumsum(values * values)],
            "x": x,
            "sumx": np.r_[0.0, np.cumsum(x)],
            "sumx2": np.r_[0.0, np.cumsum(x * x)],
            "sumxy": np.r_[0.0, np.cumsum(x * values)],
        }
    window = timedelta(hours=lookback_hours)
    records = []
    for landmark in points.itertuples(index=False):
        group = grouped.get(landmark.stay_id)
        if group is None:
            start = end = 0
            values = np.array([], dtype=float)
        else:
            landmark_time = np.datetime64(landmark.landmark_time, "ns")
            start_time = landmark_time - np.timedelta64(int(window.total_seconds()), "s")
            start = int(np.searchsorted(group["times"], start_time, side="left"))
            end = int(np.searchsorted(group["times"], landmark_time, side="left"))
            values = group["values"][start:end]
        count = end - start
        slope = np.nan
        mean = std = np.nan
        if count:
            total = group["sum"][end] - group["sum"][start]
            total_sq = group["sumsq"][end] - group["sumsq"][start]
            mean = total / count
            if count >= 2:
                variance = max(0.0, (total_sq - total * total / count) / (count - 1))
                std = float(np.sqrt(variance))
                sumx = group["sumx"][end] - group["sumx"][start]
                sumx2 = group["sumx2"][end] - group["sumx2"][start]
                sumxy = group["sumxy"][end] - group["sumxy"][start]
                denominator = count * sumx2 - sumx * sumx
                if denominator > 0:
                    slope = float((count * sumxy - sumx * total) / denominator)
        row = {key: getattr(landmark, key) for key in KEYS}
        row.update({
            f"{variable}_count_{suffix}": count,
            f"{variable}_missing_{suffix}": count == 0,
            f"{variable}_last_{suffix}": np.nan if count == 0 else float(values[-1]),
            f"{variable}_min_{suffix}": np.nan if count == 0 else float(values.min()),
            f"{variable}_max_{suffix}": np.nan if count == 0 else float(values.max()),
            f"{variable}_mean_{suffix}": mean,
            f"{variable}_std_{suffix}": std,
            f"{variable}_slope_{suffix}": slope,
            f"{variable}_hours_since_last_{suffix}": np.nan if count == 0 else float(
                (np.datetime64(landmark.landmark_time, "ns") - group["times"][end - 1])
                / np.timedelta64(1, "h")
            ),
        })
        records.append(row)
    return pd.DataFrame(records)


def multiwindow_numeric_features(
    landmarks: pd.DataFrame,
    events: pd.DataFrame,
    *,
    variable: str,
    lookbacks_hours: tuple[int, ...] = (6, 12, 24),
) -> pd.DataFrame:
    """Join features for several unique lookbacks onto one landmark key."""
    windows = tuple(dict.fromkeys(lookbacks_hours))
    if not windows:
        raise ValueError("lookbacks_hours cannot be empty")
    result = landmarks[KEYS].copy()
    for hours in windows:
        features = numeric_window_features(
            landmarks, events, variable=variable, lookback_hours=hours
        )
        result = result.merge(features, on=KEYS, how="left", validate="one_to_one")
    return result


def build_numeric_feature_matrix(
    landmarks: pd.DataFrame,
    events: pd.DataFrame,
    *,
    variables: tuple[str, ...],
    lookbacks_hours: tuple[int, ...] = (6, 12, 24),
) -> pd.DataFrame:
    """Build one predictor-only row per unique landmark."""
    _require(events, {"stay_id", "event_time", "variable", "value"}, "events")
    if not variables:
        raise ValueError("variables cannot be empty")
    if len(set(variables)) != len(variables):
        raise ValueError("variables must be unique")
    points = landmarks[KEYS].drop_duplicates().reset_index(drop=True)
    if points.duplicated(["stay_id", "landmark_time"]).any():
        raise ValueError("landmark identifiers disagree for the same stay and time")
    result = points.copy()
    for variable in variables:
        source = events.loc[
            events["variable"].eq(variable), ["stay_id", "event_time", "value"]
        ]
        block = multiwindow_numeric_features(
            points, source, variable=variable, lookbacks_hours=lookbacks_hours
        )
        result = result.merge(block, on=KEYS, how="left", validate="one_to_one")
    return result
