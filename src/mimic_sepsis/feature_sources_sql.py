"""DuckDB SQL pushdown for normalized, landmark-relevant feature events."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from .feature_sources import LAB_ITEMS, VITAL_ITEMS


def _vital_dictionary() -> pd.DataFrame:
    rows = []
    for itemid, (variable, lower, upper) in VITAL_ITEMS.items():
        rows.append({
            "itemid": itemid,
            "variable": "temperature" if variable == "temperature_f" else variable,
            "lower_bound": float(lower),
            "upper_bound": float(upper),
            "fahrenheit": variable == "temperature_f",
        })
    return pd.DataFrame(rows)


def _lab_dictionary() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "itemid": itemid,
            "variable": variable,
            "lower_bound": float(lower),
            "upper_bound": float(upper),
        }
        for itemid, (variable, lower, upper) in LAB_ITEMS.items()
    ])


def read_normalized_feature_events_sql(
    connection: duckdb.DuckDBPyConnection,
    *,
    landmark_path: str | Path,
    cohort_path: str | Path,
    chartevents_path: str | Path,
    labevents_path: str | Path,
    maximum_lookback_hours: int,
) -> pd.DataFrame:
    """Normalize and temporally prune source events before pandas materialization.

    The SQL returns a safe superset of events that can enter at least one
    landmark window in the part. The established Python window aggregator
    retains final authority over the exact ``[L-W,L)`` boundary.
    """
    if maximum_lookback_hours <= 0:
        raise ValueError("maximum_lookback_hours must be positive")
    connection.register("_feature_vital_dictionary", _vital_dictionary())
    connection.register("_feature_lab_dictionary", _lab_dictionary())
    try:
        return connection.execute(
            """
            WITH landmark_bounds AS (
              SELECT
                stay_id,
                min(CAST(landmark_time AS TIMESTAMP_NS))
                  - (? * INTERVAL '1 hour') AS earliest_event_time,
                max(CAST(landmark_time AS TIMESTAMP_NS)) AS latest_landmark_time
              FROM read_parquet(?)
              GROUP BY stay_id
            ),
            vital_candidates AS (
              SELECT
                source.stay_id,
                CAST(source.charttime AS TIMESTAMP_NS) AS event_time,
                dictionary.variable,
                CASE
                  WHEN dictionary.fahrenheit
                    THEN (TRY_CAST(source.valuenum AS DOUBLE) - 32.0) * 5.0 / 9.0
                  ELSE TRY_CAST(source.valuenum AS DOUBLE)
                END AS value,
                source.itemid,
                TRY_CAST(source.valuenum AS DOUBLE) AS raw_value,
                dictionary.lower_bound,
                dictionary.upper_bound,
                bounds.earliest_event_time,
                bounds.latest_landmark_time
              FROM read_parquet(?) source
              JOIN _feature_vital_dictionary dictionary USING (itemid)
              JOIN landmark_bounds bounds USING (stay_id)
            ),
            vital_events AS (
              SELECT stay_id, event_time, variable, value, itemid
              FROM vital_candidates
              WHERE event_time IS NOT NULL
                AND raw_value BETWEEN lower_bound AND upper_bound
                AND event_time >= earliest_event_time
                AND event_time < latest_landmark_time
            ),
            lab_candidates AS (
              SELECT
                stays.stay_id,
                CAST(source.storetime AS TIMESTAMP_NS) AS event_time,
                dictionary.variable,
                TRY_CAST(source.valuenum AS DOUBLE) AS value,
                source.itemid,
                CAST(source.charttime AS TIMESTAMP_NS) AS specimen_time,
                CAST(stays.intime AS TIMESTAMP_NS) AS intime,
                CAST(stays.outtime AS TIMESTAMP_NS) AS outtime,
                dictionary.lower_bound,
                dictionary.upper_bound,
                bounds.earliest_event_time,
                bounds.latest_landmark_time
              FROM read_parquet(?) source
              JOIN _feature_lab_dictionary dictionary USING (itemid)
              JOIN read_parquet(?) stays USING (subject_id, hadm_id)
              JOIN landmark_bounds bounds USING (stay_id)
            ),
            lab_events AS (
              SELECT stay_id, event_time, variable, value, itemid
              FROM lab_candidates
              WHERE specimen_time IS NOT NULL
                AND event_time IS NOT NULL
                AND value BETWEEN lower_bound AND upper_bound
                AND specimen_time >= intime
                AND specimen_time < outtime
                AND event_time >= earliest_event_time
                AND event_time < latest_landmark_time
            )
            SELECT * FROM vital_events
            UNION ALL
            SELECT * FROM lab_events
            ORDER BY stay_id, event_time, variable, itemid
            """,
            [
                int(maximum_lookback_hours),
                str(landmark_path),
                str(chartevents_path),
                str(labevents_path),
                str(cohort_path),
            ],
        ).fetchdf()
    finally:
        connection.unregister("_feature_vital_dictionary")
        connection.unregister("_feature_lab_dictionary")
