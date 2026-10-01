from pathlib import Path
import json

import duckdb
import pandas as pd
from pandas.testing import assert_frame_equal
import pytest

from mimic_sepsis.artifacts import ArtifactValidationError
from mimic_sepsis.chunked_sofa import (
    PIPELINE_SOURCE_ARTIFACTS, ChunkedSofaBuilder,
    partitioned_dataset_sha256, read_partitioned_dataset, validate_extract,
    validate_partitioned_dataset,
)
from mimic_sepsis.equivalence import compare_parquet
from mimic_sepsis.full_extract import FullCSVExtractor
from mimic_sepsis.sofa_demo import build_demo_hourly_sofa


def _sources() -> dict[str, pd.DataFrame]:
    cohort = pd.DataFrame({
        "subject_id": [1, 2], "hadm_id": [10, 20], "stay_id": [100, 200],
        "intime": pd.to_datetime(["2100-01-01", "2100-02-01"]),
        "outtime": pd.to_datetime(["2100-01-02", "2100-02-02"]),
        "age_at_icu": [50, 60],
    })
    chart = pd.DataFrame({
        "stay_id": [100, 100, 200, 200],
        "itemid": [220045, 220052, 220045, 220052],
        "charttime": pd.to_datetime([
            "2100-01-01 01:00", "2100-01-01 01:00",
            "2100-02-01 01:00", "2100-02-01 01:00",
        ]),
        "value": ["80", "60", "90", "75"],
        "valuenum": [80.0, 60.0, 90.0, 75.0],
    })
    labs = pd.DataFrame({
        "subject_id": [1, 2], "hadm_id": [10, 20], "itemid": [51265, 51265],
        "charttime": pd.to_datetime(["2100-01-01 01:00", "2100-02-01 01:00"]),
        "storetime": pd.to_datetime(["2100-01-01 02:00", "2100-02-01 02:00"]),
        "valuenum": [100.0, 200.0], "valueuom": ["K/uL", "K/uL"],
    })
    return {
        "cohort_stays": cohort,
        "chartevents_reduced": chart,
        "labevents_reduced": labs,
        "inputevents_reduced": pd.DataFrame({
            "stay_id": pd.Series(dtype="int64"), "itemid": pd.Series(dtype="int64"),
            "starttime": pd.Series(dtype="datetime64[ns]"),
            "endtime": pd.Series(dtype="datetime64[ns]"),
            "rate": pd.Series(dtype="float64"), "rateuom": pd.Series(dtype="str"),
        }),
        "outputevents_reduced": pd.DataFrame({
            "stay_id": pd.Series(dtype="int64"), "itemid": pd.Series(dtype="int64"),
            "charttime": pd.Series(dtype="datetime64[ns]"),
            "value": pd.Series(dtype="float64"),
        }),
        "procedureevents_reduced": pd.DataFrame({
            "stay_id": pd.Series(dtype="int64"), "itemid": pd.Series(dtype="int64"),
            "starttime": pd.Series(dtype="datetime64[ns]"),
            "endtime": pd.Series(dtype="datetime64[ns]"),
        }),
    }


def _write_extract(root: Path, frames: dict[str, pd.DataFrame]) -> None:
    extractor = FullCSVExtractor(root / "unused", root, data_version="test")
    connection = duckdb.connect()
    try:
        for name, frame in frames.items():
            connection.register("source", frame)
            extractor._write(connection, name, "SELECT * FROM source", resume=False)
            connection.unregister("source")
    finally:
        connection.close()


def test_chunked_sofa_equals_monolithic_for_multiple_batches(tmp_path):
    frames = _sources()
    source = tmp_path / "extract"
    _write_extract(source, frames)
    result = ChunkedSofaBuilder(
        source, tmp_path / "score", batch_size=1, code_version="test"
    ).run()
    assert len(result.parts) == 2

    run_root = tmp_path / "score" / result.config_sha256[:16]
    actual = duckdb.sql(
        "SELECT * FROM read_parquet(?) ORDER BY subject_id, endtime, stay_id, hr",
        params=[str(run_root / "parts" / "part-*.parquet")],
    ).df()
    expected = build_demo_hourly_sofa(
        icustays=frames["cohort_stays"],
        chartevents=frames["chartevents_reduced"],
        labevents=frames["labevents_reduced"],
        inputevents=frames["inputevents_reduced"],
        outputevents=frames["outputevents_reduced"],
        procedureevents=frames["procedureevents_reduced"],
    ).sort_values(["subject_id", "endtime", "stay_id", "hr"]).reset_index(drop=True)
    assert_frame_equal(actual, expected, check_dtype=False)
    validated = validate_partitioned_dataset(run_root, "sofa_hourly")
    assert validated.rows == len(expected)
    loaded = read_partitioned_dataset(
        run_root, "sofa_hourly", validated_manifest=validated
    ).sort_values(["subject_id", "endtime", "stay_id", "hr"]).reset_index(drop=True)
    assert_frame_equal(loaded, expected, check_dtype=False)
    assert len(partitioned_dataset_sha256(validated)) == 64
    projected = read_partitioned_dataset(
        run_root, "sofa_hourly", validated_manifest=validated,
        columns=["subject_id", "stay_id", "hr"], filters={"stay_id": 100},
    )
    assert list(projected.columns) == ["subject_id", "stay_id", "hr"]
    assert set(projected["stay_id"]) == {100}

    expected_path = tmp_path / "expected.parquet"
    connection = duckdb.connect()
    connection.register("expected", expected)
    connection.execute("COPY expected TO ? (FORMAT PARQUET)", [str(expected_path)])
    connection.close()
    comparison = compare_parquet(
        run_root / "parts" / "part-*.parquet", expected_path
    )
    assert comparison.equivalent


def test_resume_reuses_valid_parts_and_corrupt_source_fails_closed(tmp_path):
    source = tmp_path / "extract"
    _write_extract(source, _sources())
    builder = ChunkedSofaBuilder(
        source, tmp_path / "score", batch_size=1, code_version="test"
    )
    first = builder.run()
    run_root = tmp_path / "score" / first.config_sha256[:16]
    part = run_root / "parts" / "part-00000.parquet"
    modified = part.stat().st_mtime_ns
    assert builder.run(resume=True) == first
    assert part.stat().st_mtime_ns == modified

    (source / "chartevents_reduced.parquet").write_bytes(b"corrupt")
    with pytest.raises(ArtifactValidationError, match="checksum mismatch"):
        validate_extract(source)


def test_extract_validation_rejects_obsolete_extractor_schema(tmp_path):
    source = tmp_path / "extract"
    _write_extract(source, _sources())
    manifest_path = source / "labevents_reduced.manifest.json"
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw["extractor_schema_version"] = 8
    manifest_path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ArtifactValidationError, match="extractor schema version"):
        validate_extract(source)


def test_extract_validation_checks_physical_schema_and_row_count(tmp_path):
    source = tmp_path / "extract"
    _write_extract(source, _sources())
    manifest_path = source / "chartevents_reduced.manifest.json"
    original = json.loads(manifest_path.read_text(encoding="utf-8"))

    changed = {**original, "columns": [*original["columns"], "invented"]}
    manifest_path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ArtifactValidationError, match="schema mismatch"):
        validate_extract(source)

    changed = {**original, "rows": original["rows"] + 1}
    manifest_path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ArtifactValidationError, match="row count mismatch"):
        validate_extract(source)


def test_full_pipeline_validation_requires_label_sources(tmp_path):
    source = tmp_path / "extract"
    _write_extract(source, _sources())
    with pytest.raises(FileNotFoundError, match="prescriptions_cohort"):
        validate_extract(source, artifacts=PIPELINE_SOURCE_ARTIFACTS)


def test_extract_validation_rejects_missing_required_physical_column(tmp_path):
    frames = _sources()
    frames["chartevents_reduced"] = frames["chartevents_reduced"].drop(
        columns="valuenum"
    )
    source = tmp_path / "extract"
    _write_extract(source, frames)

    with pytest.raises(ArtifactValidationError, match="valuenum"):
        validate_extract(source)


def test_extract_validation_rejects_empty_or_duplicate_artifact_contract(tmp_path):
    for artifacts in ((), ("cohort_stays", "cohort_stays")):
        with pytest.raises(ValueError, match="non-empty and unique"):
            validate_extract(tmp_path, artifacts=artifacts)


def test_partition_manifest_rejects_noncanonical_part_name(tmp_path):
    source = tmp_path / "extract"
    _write_extract(source, _sources())
    result = ChunkedSofaBuilder(
        source, tmp_path / "score", batch_size=2, code_version="test"
    ).run()
    run_root = tmp_path / "score" / result.config_sha256[:16]
    manifest_path = run_root / "sofa_hourly.dataset.json"
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw["parts"][0]["name"] = "part-../../outside"
    manifest_path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ArtifactValidationError, match="Invalid.*partition"):
        validate_partitioned_dataset(run_root, "sofa_hourly")


def test_partition_projection_rejects_empty_or_duplicate_columns(tmp_path):
    source = tmp_path / "extract"
    _write_extract(source, _sources())
    result = ChunkedSofaBuilder(
        source, tmp_path / "score", batch_size=2, code_version="test"
    ).run()
    run_root = tmp_path / "score" / result.config_sha256[:16]
    for columns in ([], ["stay_id", "stay_id"]):
        with pytest.raises(ValueError, match="non-empty and unique"):
            read_partitioned_dataset(
                run_root, "sofa_hourly", columns=columns
            )
