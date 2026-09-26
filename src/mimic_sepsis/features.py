"""Leakage-safe numeric feature aggregation before prediction landmarks."""

from __future__ import annotations

import numpy as np
import pandas as pd


KEYS = ["subject_id", "hadm_id", "stay_id", "landmark_time"]


def _require(frame: pd.DataFrame, columns: set[str], name: str) -> None:
    missing = sorted(columns - set(frame.columns))
    if missing:
        raise ValueError(f"{name} is missing columns: {', '.join(missing)}")


def _prepare_landmarks(landmarks: pd.DataFrame) -> pd.DataFrame:
    _require(landmarks, set(KEYS), "landmarks")
    if landmarks.duplicated(["stay_id", "landmark_time"]).any():
        raise ValueError("landmarks must be unique by stay_id and landmark_time")
    points = landmarks[KEYS].reset_index(drop=True).copy()
    points["landmark_time"] = pd.to_datetime(
        points["landmark_time"], errors="raise", format="mixed"
    )
    return points


def _prepare_event_groups(events: pd.DataFrame) -> dict:
    _require(events, {"stay_id", "event_time", "value"}, "events")
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
            "sumx": np.r_[0.0, np.cumsum(x)],
            "sumx2": np.r_[0.0, np.cumsum(x * x)],
            "sumxy": np.r_[0.0, np.cumsum(x * values)],
        }
    return grouped


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
    if not variable or not variable.replace("_", "").isalnum():
        raise ValueError("variable must be a non-empty alphanumeric snake-case name")
    points = _prepare_landmarks(landmarks)
    grouped = _prepare_event_groups(events)
    return _numeric_window_features_prepared(
        points, grouped, variable=variable, lookback_hours=lookback_hours
    )


def _numeric_window_features_prepared(
    points: pd.DataFrame,
    grouped: dict,
    *,
    variable: str,
    lookback_hours: int,
) -> pd.DataFrame:
    if lookback_hours <= 0:
        raise ValueError("lookback_hours must be positive")
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
    size = len(points)
    counts = np.zeros(size, dtype=np.int64)
    last = np.full(size, np.nan)
    minimum = np.full(size, np.nan)
    maximum = np.full(size, np.nan)
    means = np.full(size, np.nan)
    standard_deviations = np.full(size, np.nan)
    slopes = np.full(size, np.nan)
    hours_since_last = np.full(size, np.nan)
    point_groups = points.groupby("stay_id", sort=False).indices
    window = np.timedelta64(lookback_hours, "h")
    for stay_id, positions in point_groups.items():
        group = grouped.get(stay_id)
        if group is None:
            continue
        positions = np.asarray(positions, dtype=np.int64)
        landmark_times = points.loc[positions, "landmark_time"].to_numpy(
            dtype="datetime64[ns]"
        )
        starts = np.searchsorted(
            group["times"], landmark_times - window, side="left"
        )
        ends = np.searchsorted(group["times"], landmark_times, side="left")
        group_counts = ends - starts
        counts[positions] = group_counts
        present = group_counts > 0
        if not present.any():
            continue
        present_positions = positions[present]
        present_starts = starts[present]
        present_ends = ends[present]
        present_counts = group_counts[present]
        totals = group["sum"][present_ends] - group["sum"][present_starts]
        total_squares = (
            group["sumsq"][present_ends] - group["sumsq"][present_starts]
        )
        means[present_positions] = totals / present_counts
        last[present_positions] = group["values"][present_ends - 1]
        hours_since_last[present_positions] = (
            landmark_times[present] - group["times"][present_ends - 1]
        ) / np.timedelta64(1, "h")
        for position, start, end in zip(
            present_positions, present_starts, present_ends, strict=True
        ):
            values = group["values"][start:end]
            minimum[position] = values.min()
            maximum[position] = values.max()

        repeated = present_counts >= 2
        if repeated.any():
            repeated_positions = present_positions[repeated]
            repeated_starts = present_starts[repeated]
            repeated_ends = present_ends[repeated]
            repeated_counts = present_counts[repeated]
            repeated_totals = totals[repeated]
            variance = (
                total_squares[repeated]
                - repeated_totals * repeated_totals / repeated_counts
            ) / (repeated_counts - 1)
            standard_deviations[repeated_positions] = np.sqrt(
                np.maximum(0.0, variance)
            )
            sum_x = (
                group["sumx"][repeated_ends] - group["sumx"][repeated_starts]
            )
            sum_x2 = (
                group["sumx2"][repeated_ends] - group["sumx2"][repeated_starts]
            )
            sum_xy = (
                group["sumxy"][repeated_ends] - group["sumxy"][repeated_starts]
            )
            denominator = repeated_counts * sum_x2 - sum_x * sum_x
            estimable = denominator > 0
            slopes[repeated_positions[estimable]] = (
                repeated_counts[estimable] * sum_xy[estimable]
                - sum_x[estimable] * repeated_totals[estimable]
            ) / denominator[estimable]

    result = points.copy()
    result[f"{variable}_count_{suffix}"] = counts
    result[f"{variable}_missing_{suffix}"] = counts == 0
    result[f"{variable}_last_{suffix}"] = last
    result[f"{variable}_min_{suffix}"] = minimum
    result[f"{variable}_max_{suffix}"] = maximum
    result[f"{variable}_mean_{suffix}"] = means
    result[f"{variable}_std_{suffix}"] = standard_deviations
    result[f"{variable}_slope_{suffix}"] = slopes
    result[f"{variable}_hours_since_last_{suffix}"] = hours_since_last
    return result


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
    if not variable or not variable.replace("_", "").isalnum():
        raise ValueError("variable must be a non-empty alphanumeric snake-case name")
    points = _prepare_landmarks(landmarks)
    grouped = _prepare_event_groups(events)
    result: pd.DataFrame | None = None
    for hours in windows:
        features = _numeric_window_features_prepared(
            points, grouped, variable=variable, lookback_hours=hours
        )
        if result is None:
            result = features
            continue
        if not result[KEYS].equals(features[KEYS]):
            raise RuntimeError("Feature windows changed landmark row order")
        result = pd.concat(
            [result, features.drop(columns=KEYS)], axis="columns", copy=False
        )
    if result is None:  # Guarded by the non-empty windows check above.
        raise RuntimeError("No feature windows were built")
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
    result: pd.DataFrame | None = None
    for variable in variables:
        source = events.loc[
            events["variable"].eq(variable), ["stay_id", "event_time", "value"]
        ]
        block = multiwindow_numeric_features(
            points, source, variable=variable, lookbacks_hours=lookbacks_hours
        )
        if result is None:
            result = block
            continue
        if not result[KEYS].equals(block[KEYS]):
            raise RuntimeError("Feature variables changed landmark row order")
        result = pd.concat(
            [result, block.drop(columns=KEYS)], axis="columns", copy=False
        )
    if result is None:  # Guarded by the non-empty variables check above.
        raise RuntimeError("No feature variables were built")
    return result
