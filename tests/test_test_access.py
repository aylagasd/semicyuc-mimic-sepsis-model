import hashlib
import json

import pytest

from mimic_sepsis.artifacts import ArtifactValidationError
from mimic_sepsis.chunked_features import ChunkedFeatureBuilder
from mimic_sepsis.chunked_landmarks import (
    ChunkedLandmarkBuilder,
    validate_partitions,
)
from mimic_sepsis.test_access import validate_test_release


def _files(tmp_path, *, status="frozen", data_version="3.1", roles=None):
    freeze = tmp_path / "model_freeze.json"
    freeze.write_text(json.dumps({
        "schema_version": 1,
        "status": status,
        "test_access": "locked_until_release",
        "frozen_at_utc": "2026-09-23T09:00:00Z",
        "data_version": data_version,
        "source_run_id": "full-3.1-example",
        "code_commit": "abcdef1234567890",
        "primary_target": "sepsis3",
        "horizon_hours": 6,
        "feature_columns": ["heart_rate_last_24h", "map_min_24h"],
        "primary_model": "logistic",
        "model_parameters": {"C": 1.0},
        "calibration": {"method": "none", "intercept": None, "slope": None},
        "operating_thresholds": [0.05, 0.1],
        "decision_statuses": {
            key: "frozen" for key in (
                "D002", "D004", "D010", "D011", "D014", "D016", "D027", "D029",
                "D031",
            )
        },
        "validation_report_sha256": "a" * 64,
    }))
    digest = hashlib.sha256(freeze.read_bytes()).hexdigest()
    release = tmp_path / "test_release.local.json"
    release.write_text(json.dumps({
        "schema_version": 1,
        "approval_status": "approved",
        "approved_at_utc": "2026-09-23T10:00:00Z",
        "approver_roles": roles or ["clinical_lead", "statistical_lead"],
        "data_version": data_version,
        "model_freeze_sha256": digest,
        "reason": "Single prespecified final evaluation after model freeze.",
    }))
    return release, freeze


def test_release_is_bound_to_frozen_model_and_data_version(tmp_path):
    release, freeze = _files(tmp_path)
    result = validate_test_release(
        release, freeze, expected_data_version="3.1"
    )
    assert result.data_version == "3.1"
    assert result.approver_roles == ("clinical_lead", "statistical_lead")


def test_release_rejects_draft_model(tmp_path):
    release, freeze = _files(tmp_path, status="draft")
    with pytest.raises(ValueError, match="not frozen"):
        validate_test_release(release, freeze, expected_data_version="3.1")


def test_release_rejects_missing_independent_role(tmp_path):
    release, freeze = _files(tmp_path, roles=["clinical_lead"])
    with pytest.raises(ValueError, match="clinical and statistical"):
        validate_test_release(release, freeze, expected_data_version="3.1")


def test_release_rejects_modified_model_freeze(tmp_path):
    release, freeze = _files(tmp_path)
    freeze.write_text(freeze.read_text() + "\n")
    with pytest.raises(ValueError, match="not bound"):
        validate_test_release(release, freeze, expected_data_version="3.1")


def test_release_rejects_wrong_data_version(tmp_path):
    release, freeze = _files(tmp_path, data_version="2.2")
    with pytest.raises(ValueError, match="data_version"):
        validate_test_release(release, freeze, expected_data_version="3.1")


def test_partition_selection_rejects_unknown_or_duplicate_values():
    assert validate_partitions(("development", "validation")) == (
        "development", "validation",
    )
    with pytest.raises(ValueError, match="unique"):
        validate_partitions(("development", "development"))
    with pytest.raises(ValueError, match="Unknown"):
        validate_partitions(("development", "future"))


@pytest.mark.parametrize("builder_name", ["landmarks", "features"])
def test_non_demo_builders_refuse_test_without_gated_pipeline(
    tmp_path, monkeypatch, builder_name,
):
    source_manifest = type("Manifest", (), {"data_version": "3.1"})()
    if builder_name == "landmarks":
        monkeypatch.setattr(
            "mimic_sepsis.chunked_landmarks.validate_extract",
            lambda _: {"cohort": source_manifest},
        )
        builder = ChunkedLandmarkBuilder(
            tmp_path, tmp_path, tmp_path, tmp_path,
            landmark_config_path=tmp_path / "landmarks.json",
            split_config_path=tmp_path / "splits.json",
        )
    else:
        monkeypatch.setattr(
            "mimic_sepsis.chunked_features.validate_extract",
            lambda _: {"cohort": source_manifest},
        )
        builder = ChunkedFeatureBuilder(
            tmp_path, tmp_path, tmp_path,
            feature_config_path=tmp_path / "features.json",
        )
    with pytest.raises(ArtifactValidationError, match="gated full pipeline"):
        builder.run()
