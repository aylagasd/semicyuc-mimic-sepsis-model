from dataclasses import asdict
import json
from pathlib import Path
from types import SimpleNamespace

import duckdb
import pandas as pd
import pytest

from mimic_sepsis.artifacts import ArtifactStore, ArtifactValidationError
from mimic_sepsis.chunked_sofa import PartitionedDatasetManifest
from mimic_sepsis.pretest_inputs import (
    load_partitioned_pretest_config, load_partitioned_pretest_inputs,
)


def _write_parquet(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    try:
        connection.register("frame", frame)
        connection.execute("COPY frame TO ? (FORMAT PARQUET)", [str(path)])
    finally:
        connection.close()


def _write_dataset(root: Path, name: str, frame: pd.DataFrame, partition: str):
    store = ArtifactStore(root / name / "parts")
    part = store.write_dataframe(
        "part-00000", frame, data_version="3.1",
        code_version="test", config={"partition": partition},
    )
    manifest = PartitionedDatasetManifest(
        artifact=name, data_version="3.1", config_sha256="a" * 64,
        rows=len(frame),
        parts=({"name": "part-00000", "rows": len(frame), "sha256": part.sha256},),
        metadata={"patient_partition": partition},
    )
    (root / name / f"{name}.dataset.json").write_text(
        json.dumps(asdict(manifest)), encoding="utf-8"
    )


def _inputs(tmp_path: Path):
    source = tmp_path / "extract"
    cohort = pd.DataFrame({
        "subject_id": [1, 2], "hadm_id": [10, 20], "stay_id": [100, 200],
    })
    _write_parquet(source / "cohort_stays.parquet", cohort)
    landmarks = tmp_path / "landmarks" / "landmark-run"
    features = tmp_path / "features" / "feature-run"
    for partition, subject, stay in (("development", 1, 100), ("validation", 2, 200)):
        key = {
            "subject_id": [subject], "hadm_id": [subject * 10],
            "stay_id": [stay], "landmark_time": pd.to_datetime(["2100-01-01"]),
        }
        _write_dataset(
            landmarks, f"sepsis3_{partition}_landmarks",
            pd.DataFrame({**key, "horizon_hours": [6], "horizon_observed": [True],
                          "outcome": [partition == "validation"],
                          "event_time": pd.to_datetime([None])}), partition,
        )
        _write_dataset(
            features, f"sepsis3_{partition}_features",
            pd.DataFrame({**key, "heart_rate_last_24h": [80.0]}), partition,
        )
    return source, landmarks, features


def _mock_extract(monkeypatch):
    manifests = {
        "cohort_stays": SimpleNamespace(data_version="3.1", sha256="b" * 64),
        "other": SimpleNamespace(data_version="3.1", sha256="c" * 64),
    }
    monkeypatch.setattr(
        "mimic_sepsis.pretest_inputs.validate_extract", lambda _: manifests
    )


def test_partitioned_pretest_loader_keeps_only_disjoint_development_validation(
    tmp_path, monkeypatch,
):
    source, landmarks, features = _inputs(tmp_path)
    _mock_extract(monkeypatch)
    bundle = load_partitioned_pretest_inputs(source, landmarks, features)
    assert bundle.data_version == "3.1"
    assert bundle.target == "sepsis3"
    assert set(bundle.landmarks) == {"development", "validation"}
    assert set(bundle.landmarks["development"].subject_id) == {1}
    assert set(bundle.landmarks["validation"].subject_id) == {2}
    assert "test" not in bundle.landmarks
    assert len(bundle.source_artifacts) == 5


def test_partitioned_pretest_loader_rejects_patient_leakage(tmp_path, monkeypatch):
    source, landmarks, features = _inputs(tmp_path)
    _mock_extract(monkeypatch)
    validation = pd.DataFrame({
        "subject_id": [1], "hadm_id": [10], "stay_id": [100],
        "landmark_time": pd.to_datetime(["2100-01-01"]),
        "horizon_hours": [6], "horizon_observed": [True], "outcome": [0],
    })
    _write_dataset(
        landmarks, "sepsis3_validation_landmarks", validation, "validation"
    )
    validation_features = validation[
        ["subject_id", "hadm_id", "stay_id", "landmark_time"]
    ].assign(heart_rate_last_24h=80.0)
    _write_dataset(
        features, "sepsis3_validation_features", validation_features, "validation"
    )
    with pytest.raises(ArtifactValidationError, match="Patient leakage"):
        load_partitioned_pretest_inputs(source, landmarks, features)


def test_partitioned_pretest_loader_rejects_label_columns_in_features(
    tmp_path, monkeypatch,
):
    source, landmarks, features = _inputs(tmp_path)
    _mock_extract(monkeypatch)
    bad = pd.DataFrame({
        "subject_id": [1], "hadm_id": [10], "stay_id": [100],
        "landmark_time": pd.to_datetime(["2100-01-01"]),
        "heart_rate_last_24h": [80.0], "outcome": [1],
    })
    _write_dataset(features, "sepsis3_development_features", bad, "development")
    with pytest.raises(ArtifactValidationError, match="label/partition"):
        load_partitioned_pretest_inputs(source, landmarks, features)


def test_local_config_rejects_unknown_backend(tmp_path):
    path = tmp_path / "source.json"
    path.write_text(
        json.dumps({"schema_version": 1, "backend": "database"}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Unsupported"):
        load_partitioned_pretest_config(path)


def test_loader_projects_features_and_primary_observed_horizon(
    tmp_path, monkeypatch,
):
    source, landmarks, features = _inputs(tmp_path)
    _mock_extract(monkeypatch)
    development = pd.DataFrame({
        "subject_id": [1, 1, 1], "hadm_id": [10, 10, 10],
        "stay_id": [100, 100, 100],
        "landmark_time": pd.to_datetime([
            "2100-01-01", "2100-01-01", "2100-01-01 01:00",
        ], format="mixed"),
        "horizon_hours": [6, 12, 6],
        "horizon_observed": [True, True, False],
        "outcome": [0, 1, pd.NA],
        "event_time": pd.to_datetime([None, None, None]),
    })
    _write_dataset(
        landmarks, "sepsis3_development_landmarks", development, "development"
    )
    development_features = pd.DataFrame({
        "subject_id": [1, 1], "hadm_id": [10, 10], "stay_id": [100, 100],
        "landmark_time": pd.to_datetime(
            ["2100-01-01", "2100-01-01 01:00"], format="mixed"
        ),
        "heart_rate_last_24h": [80.0, 81.0],
        "unused_feature": [999.0, 999.0],
    })
    _write_dataset(
        features, "sepsis3_development_features",
        development_features, "development",
    )
    bundle = load_partitioned_pretest_inputs(
        source, landmarks, features,
        feature_columns=["heart_rate_last_24h"], horizon_hours=6,
    )
    assert len(bundle.landmarks["development"]) == 1
    assert bundle.landmarks["development"]["horizon_hours"].eq(6).all()
    assert bundle.landmarks["development"]["horizon_observed"].all()
    assert list(bundle.features["development"].columns) == [
        "subject_id", "hadm_id", "stay_id", "landmark_time",
        "heart_rate_last_24h",
    ]
