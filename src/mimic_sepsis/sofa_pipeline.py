"""Composition helpers for hourly SOFA component tables."""

from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd


COMPONENTS = ("respiratory", "coagulation", "liver", "cardiovascular", "cns", "renal")


def rolling_interval_worst_score(
    grid: pd.DataFrame,
    intervals: pd.DataFrame,
    *,
    window_hours: int = 24,
) -> pd.DataFrame:
    """Maximum score from intervals overlapping ``(end-window, end]``."""
    required_grid = {"stay_id", "hr", "endtime"}
    required_intervals = {"stay_id", "starttime", "endtime", "score"}
    for frame, required, name in [
        (grid, required_grid, "grid"), (intervals, required_intervals, "intervals")
    ]:
        missing = sorted(required - set(frame.columns))
        if missing:
            raise ValueError(f"{name} is missing columns: {', '.join(missing)}")
    if window_hours <= 0:
        raise ValueError("window_hours must be positive")
    result = grid.copy()
    result["endtime"] = pd.to_datetime(result["endtime"], errors="raise", format="mixed")
    events = intervals.copy()
    events["starttime"] = pd.to_datetime(events["starttime"], errors="coerce", format="mixed")
    events["endtime"] = pd.to_datetime(events["endtime"], errors="coerce", format="mixed")
    events = events.dropna(subset=["starttime", "endtime", "score"])
    events = events.loc[events["endtime"].gt(events["starttime"])]
    grouped = {key: group for key, group in events.groupby("stay_id")}
    delta = timedelta(hours=window_hours)
    result["_row_order"] = np.arange(len(result))
    chunks = []
    for stay_id, stay_grid in result.groupby("stay_id", sort=False):
        chunk = stay_grid.copy()
        stay = grouped.get(stay_id)
        if stay is None:
            values = [None] * len(chunk)
        else:
            starts = stay["starttime"].to_numpy(dtype="datetime64[ns]")
            ends = stay["endtime"].to_numpy(dtype="datetime64[ns]")
            scores = stay["score"].to_numpy(dtype=int)
            values = []
            for endpoint in chunk["endtime"].to_numpy(dtype="datetime64[ns]"):
                window_start = endpoint - np.timedelta64(int(delta.total_seconds()), "s")
                overlap = (starts <= endpoint) & (ends > window_start)
                values.append(None if not overlap.any() else int(scores[overlap].max()))
        chunk["score_24h"] = pd.array(values, dtype="Int64")
        chunks.append(chunk)
    return pd.concat(chunks).sort_values("_row_order").drop(columns="_row_order")


def assemble_hourly_sofa(
    grid: pd.DataFrame,
    component_tables: dict[str, pd.DataFrame],
    *,
    missing_components_as_zero: bool = True,
) -> pd.DataFrame:
    """Join six one-row-per-grid component tables and calculate audited total."""
    missing_names = sorted(set(COMPONENTS) - set(component_tables))
    if missing_names:
        raise ValueError(f"Missing SOFA component tables: {', '.join(missing_names)}")
    keys = [column for column in ["subject_id", "hadm_id", "stay_id", "hr", "endtime"] if column in grid]
    result = grid[keys].copy()
    if result.duplicated(["stay_id", "hr"]).any():
        raise ValueError("Grid must be unique by stay_id and hr")
    for component in COMPONENTS:
        table = component_tables[component]
        required = {"stay_id", "hr", "score_24h"}
        missing = sorted(required - set(table.columns))
        if missing:
            raise ValueError(f"{component} table is missing columns: {', '.join(missing)}")
        if table.duplicated(["stay_id", "hr"]).any():
            raise ValueError(f"{component} table is not unique by stay_id and hr")
        result = result.merge(
            table[["stay_id", "hr", "score_24h"]].rename(
                columns={"score_24h": f"sofa_{component}"}
            ),
            on=["stay_id", "hr"], how="left", validate="one_to_one",
        )
    component_columns = [f"sofa_{name}" for name in COMPONENTS]
    result["missing_components"] = result[component_columns].isna().sum(axis=1)
    result["sofa_complete"] = result[component_columns].sum(axis=1, min_count=6).astype("Int64")
    if missing_components_as_zero:
        result["sofa_total"] = result[component_columns].fillna(0).sum(axis=1).astype("Int64")
    else:
        result["sofa_total"] = result["sofa_complete"]
    return result
