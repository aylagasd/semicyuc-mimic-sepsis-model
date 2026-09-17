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
