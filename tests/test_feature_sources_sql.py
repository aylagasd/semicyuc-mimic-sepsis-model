from pathlib import Path

import duckdb
import pandas as pd
from pandas.testing import assert_frame_equal
import pytest

from mimic_sepsis.feature_sources import (
    normalize_lab_feature_events, normalize_vital_events,
)
from mimic_sepsis.feature_sources_sql import read_normalized_feature_events_sql
from mimic_sepsis.features import build_numeric_feature_matrix


def _write(path: Path, frame: pd.DataFrame) -> None:
    connection = duckdb.connect()
    try:
        connection.register("frame", frame)
        connection.execute("COPY frame TO ? (FORMAT PARQUET)", [str(path)])
    finally:
        connection.close()


def test_sql_pushdown_preserves_python_feature_matrix(tmp_path):
    landmarks = pd.DataFrame({
        "subject_id": [1, 1], "hadm_id": [10, 10], "stay_id": [100, 100],
        "landmark_time": pd.to_datetime([
            "2100-01-02 06:00", "2100-01-02 08:00",
        ]),
    })
    cohort = pd.DataFrame({
        "subject_id": [1], "hadm_id": [10], "stay_id": [100],
        "intime": pd.to_datetime(["2100-01-01 00:00"]),
        "outtime": pd.to_datetime(["2100-01-03 00:00"]),
    })
    chart = pd.DataFrame({
        "stay_id": [100] * 6,
        "itemid": [220045, 220045, 220045, 220045, 223761, 220052],
        "charttime": pd.to_datetime([
            "2100-01-01 05:00",  # Outside every 24 h window.
            "2100-01-02 05:00",
            "2100-01-02 07:00",
            "2100-01-02 08:00",  # Right boundary is excluded.
            "2100-01-02 05:30",
            "2100-01-02 06:30",
        ]),
        "valuenum": [70.0, 80.0, 90.0, 100.0, 98.6, 999.0],
    })
    labs = pd.DataFrame({
        "subject_id": [1, 1, 1, 1], "hadm_id": [10, 10, 10, 10],
        "itemid": [50912, 51265, 50813, 50885],
        "charttime": pd.to_datetime([
            "2100-01-02 04:00", "2100-01-02 05:00",
            "2099-12-31 23:00", "2100-01-02 05:00",
        ]),
        "storetime": pd.to_datetime([
            "2100-01-02 05:30", "2100-01-02 06:30",
            "2100-01-02 05:00", None,
        ]),
        "valuenum": [1.2, 200.0, 2.0, 1.0],
    })
    paths = {
        "landmarks": tmp_path / "landmarks.parquet",
        "cohort": tmp_path / "cohort.parquet",
        "chart": tmp_path / "chart.parquet",
        "labs": tmp_path / "labs.parquet",
    }
    for name, frame in {
        "landmarks": landmarks, "cohort": cohort,
        "chart": chart, "labs": labs,
    }.items():
        _write(paths[name], frame)

    expected_events = pd.concat([
        normalize_vital_events(chart),
        normalize_lab_feature_events(labs, cohort),
    ], ignore_index=True)
    connection = duckdb.connect()
    try:
        actual_events = read_normalized_feature_events_sql(
            connection,
            landmark_path=paths["landmarks"],
            cohort_path=paths["cohort"],
            chartevents_path=paths["chart"],
            labevents_path=paths["labs"],
            maximum_lookback_hours=24,
        )
    finally:
        connection.close()
    variables = ("heart_rate", "map", "temperature", "creatinine", "platelets")
    expected = build_numeric_feature_matrix(
        landmarks, expected_events, variables=variables,
        lookbacks_hours=(6, 24),
    )
    actual = build_numeric_feature_matrix(
        landmarks, actual_events, variables=variables,
        lookbacks_hours=(6, 24),
    )
    assert_frame_equal(actual, expected, check_dtype=False)
    assert len(actual_events) < len(expected_events)


def test_sql_pushdown_requires_positive_lookback(tmp_path):
    connection = duckdb.connect()
    try:
        with pytest.raises(ValueError, match="positive"):
            read_normalized_feature_events_sql(
                connection,
                landmark_path=tmp_path / "missing",
                cohort_path=tmp_path / "missing",
                chartevents_path=tmp_path / "missing",
                labevents_path=tmp_path / "missing",
                maximum_lookback_hours=0,
            )
    finally:
        connection.close()


def test_sql_pushdown_accepts_multiple_landmark_parts(tmp_path):
    cohort = pd.DataFrame({
        "subject_id": [1], "hadm_id": [10], "stay_id": [100],
        "intime": pd.to_datetime(["2100-01-01"]),
        "outtime": pd.to_datetime(["2100-01-03"]),
    })
    chart = pd.DataFrame({
        "stay_id": [100, 100], "itemid": [220045, 220045],
        "charttime": pd.to_datetime(["2100-01-02 05:00", "2100-01-02 07:00"]),
        "valuenum": [80.0, 90.0],
    })
    labs = pd.DataFrame({
        "subject_id": pd.Series(dtype="int64"),
        "hadm_id": pd.Series(dtype="int64"),
        "itemid": pd.Series(dtype="int64"),
        "charttime": pd.Series(dtype="datetime64[ns]"),
        "storetime": pd.Series(dtype="datetime64[ns]"),
        "valuenum": pd.Series(dtype="float64"),
    })
    first = pd.DataFrame({
        "stay_id": [100],
        "landmark_time": pd.to_datetime(["2100-01-02 06:00"]),
    })
    second = pd.DataFrame({
        "stay_id": [100],
        "landmark_time": pd.to_datetime(["2100-01-02 08:00"]),
    })
    paths = {}
    for name, frame in {
        "cohort": cohort, "chart": chart, "labs": labs,
        "first": first, "second": second,
    }.items():
        paths[name] = tmp_path / f"{name}.parquet"
        _write(paths[name], frame)

    connection = duckdb.connect()
    try:
        events = read_normalized_feature_events_sql(
            connection,
            landmark_path=[paths["first"], paths["second"]],
            cohort_path=paths["cohort"],
            chartevents_path=paths["chart"],
            labevents_path=paths["labs"],
            maximum_lookback_hours=6,
        )
    finally:
        connection.close()

    assert events["value"].tolist() == [80.0, 90.0]
