import json

import duckdb
import pytest

from mimic_sepsis.full_extract import FullCSVExtractor, _hash_file


def _extractor(tmp_path):
    return FullCSVExtractor(
        tmp_path / "source",
        tmp_path / "derived",
        data_version="test-version",
        memory_limit="256MB",
    )


def test_write_creates_manifest_and_resumes_verified_artifact(tmp_path):
    extractor = _extractor(tmp_path)
    connection = duckdb.connect()
    try:
        first = extractor._write(
            connection, "sample", "SELECT 1 AS value", resume=False
        )
        target = extractor.output_dir / "sample.parquet"
        assert first.rows == 1
        assert first.columns == ("value",)
        assert first.sha256 == _hash_file(target)

        second = extractor._write(
            connection, "sample", "SELECT 2 AS value", resume=True
        )
        assert second == first
        assert connection.execute(
            f"SELECT value FROM read_parquet('{target}')"
        ).fetchone() == (1,)
    finally:
        connection.close()


def test_write_rebuilds_corrupt_artifact_and_cleans_failed_partial(tmp_path):
    extractor = _extractor(tmp_path)
    connection = duckdb.connect()
    try:
        extractor._write(connection, "sample", "SELECT 1 AS value", resume=False)
        target = extractor.output_dir / "sample.parquet"
        target.write_bytes(b"corrupt")

        rebuilt = extractor._write(
            connection, "sample", "SELECT 2 AS value", resume=True
        )
        assert rebuilt.sha256 == _hash_file(target)
        assert connection.execute(
            f"SELECT value FROM read_parquet('{target}')"
        ).fetchone() == (2,)

        with pytest.raises(duckdb.Error):
            extractor._write(connection, "broken", "SELECT missing", resume=False)
        assert not (extractor.output_dir / ".broken.partial.parquet").exists()
    finally:
        connection.close()


def test_manifest_does_not_contain_source_path(tmp_path):
    extractor = _extractor(tmp_path)
    connection = duckdb.connect()
    try:
        extractor._write(connection, "sample", "SELECT 1 AS value", resume=False)
    finally:
        connection.close()
    raw = json.loads(
        (extractor.output_dir / "sample.manifest.json").read_text(encoding="utf-8")
    )
    assert set(raw) == {
        "artifact", "columns", "config_sha256", "data_version", "rows", "sha256"
    }
    assert str(extractor.data_dir) not in json.dumps(raw)


def test_cohort_policy_and_age_are_bound_to_extract_identity(tmp_path):
    primary = FullCSVExtractor(
        tmp_path / "source", tmp_path / "primary",
        data_version="test", stay_policy="first_per_admission",
    )
    patient = FullCSVExtractor(
        tmp_path / "source", tmp_path / "patient",
        data_version="test", stay_policy="first_per_patient",
    )
    older = FullCSVExtractor(
        tmp_path / "source", tmp_path / "older",
        data_version="test", minimum_age=65,
    )
    assert primary.config["cohort_policy"] == "first_per_admission"
    assert patient.config["cohort_policy"] == "first_per_patient"
    assert len({primary.config_hash, patient.config_hash, older.config_hash}) == 3


def test_extract_rejects_invalid_cohort_configuration(tmp_path):
    with pytest.raises(ValueError, match="minimum_age"):
        FullCSVExtractor(
            tmp_path / "source", tmp_path / "derived",
            data_version="test", minimum_age=-1,
        )
    with pytest.raises(ValueError):
        FullCSVExtractor(
            tmp_path / "source", tmp_path / "derived",
            data_version="test", stay_policy="unreviewed",
        )
