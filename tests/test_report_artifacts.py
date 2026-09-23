from dataclasses import replace

import pandas as pd
import pytest

from mimic_sepsis.artifacts import ArtifactValidationError
from mimic_sepsis.report_artifacts import (
    REPORT_TABLES,
    implementation_sha256,
    read_aggregate_report,
    write_aggregate_report,
)
from mimic_sepsis.reporting import DevelopmentReport


def _report():
    tables = {
        name: pd.DataFrame({"metric": [name], "estimate": [0.5]})
        for name in REPORT_TABLES
    }
    return DevelopmentReport(**tables)


def test_aggregate_report_round_trip_and_content_hash(tmp_path):
    config = {"source": "demo", "schema_version": 1}
    manifest = write_aggregate_report(
        _report(), tmp_path, data_version="2.2",
        code_version="abc1234", config=config,
    )
    loaded, validated = read_aggregate_report(tmp_path, expected_config=config)
    assert validated.report_sha256 == manifest.report_sha256
    assert set(loaded.point_metrics["metric"]) == {"point_metrics"}


def test_aggregate_report_rejects_patient_identifiers(tmp_path):
    report = _report()
    report.point_metrics["stay_id"] = 123
    with pytest.raises(ValueError, match="row identifiers"):
        write_aggregate_report(
            report, tmp_path, data_version="2.2",
            code_version="abc1234", config={"source": "demo"},
        )


def test_aggregate_report_rejects_visible_suppressed_counts(tmp_path):
    report = _report()
    report = replace(report, subgroup_performance=pd.DataFrame({
        "privacy_suppressed": [True], "events": [1],
    }))
    with pytest.raises(ValueError, match="Suppressed counts"):
        write_aggregate_report(
            report, tmp_path, data_version="2.2",
            code_version="abc1234", config={"source": "demo"},
        )
    assert not list(tmp_path.glob("*.parquet"))


def test_aggregate_report_detects_tampered_table(tmp_path):
    config = {"source": "demo"}
    write_aggregate_report(
        _report(), tmp_path, data_version="2.2",
        code_version="abc1234", config=config,
    )
    path = tmp_path / "point_metrics.parquet"
    path.write_bytes(path.read_bytes() + b"tampered")
    with pytest.raises(ArtifactValidationError, match="checksum"):
        read_aggregate_report(tmp_path, expected_config=config)


def test_implementation_hash_changes_with_file_content(tmp_path):
    path = tmp_path / "module.py"
    path.write_text("value = 1\n")
    first = implementation_sha256((path,))
    path.write_text("value = 2\n")
    assert implementation_sha256((path,)) != first
