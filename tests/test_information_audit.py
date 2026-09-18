import duckdb
import pandas as pd
import pytest

from mimic_sepsis.information_audit import audit_development_information


def _write(path, frame):
    connection = duckdb.connect()
    try:
        connection.register("frame", frame)
        connection.execute("COPY frame TO ? (FORMAT PARQUET)", [str(path)])
    finally:
        connection.close()


def test_information_audit_counts_clusters_events_and_censoring(tmp_path):
    landmarks = tmp_path / "landmarks.parquet"
    features = tmp_path / "features.parquet"
    _write(landmarks, pd.DataFrame({
        "subject_id": [1, 1, 2, 3], "stay_id": [10, 10, 20, 30],
        "target": ["sepsis3"] * 4, "horizon_hours": [6] * 4,
        "outcome": pd.array([0, 1, 0, pd.NA], dtype="Int8"),
        "partition": ["development"] * 4,
    }))
    _write(features, pd.DataFrame({
        "subject_id": [1], "hadm_id": [5], "stay_id": [10],
        "landmark_time": pd.to_datetime(["2100-01-01"]),
        "a": [1.0], "b": [2.0], "c": [3.0],
    }))
    result = audit_development_information(
        landmarks, features, target="sepsis3", horizon_hours=6,
        baseline_features=("a", "b"), anticipated_cox_snell_r2=None,
    )
    assert (result.observed_landmarks, result.positive_landmarks) == (3, 1)
    assert (result.patients, result.patients_with_event, result.stays) == (3, 1, 3)
    assert result.censored_landmarks == 1
    assert result.available_engineered_predictors == 3
    assert not result.formal_sample_size_ready


def test_information_audit_fails_closed_on_nondevelopment_rows(tmp_path):
    landmarks = tmp_path / "landmarks.parquet"
    features = tmp_path / "features.parquet"
    _write(landmarks, pd.DataFrame({
        "partition": ["test"], "target": ["sepsis3"], "horizon_hours": [6],
        "outcome": [0], "subject_id": [1], "stay_id": [1],
    }))
    _write(features, pd.DataFrame({"a": [1]}))
    with pytest.raises(ValueError, match="development.*only"):
        audit_development_information(
            landmarks, features, target="sepsis3", horizon_hours=6,
            baseline_features=("a",), anticipated_cox_snell_r2=None,
        )
