from pathlib import Path

import duckdb
import pandas as pd
import pytest

from mimic_sepsis.chunked_labels import ChunkedLabelBuilder


def _builder(tmp_path: Path) -> ChunkedLabelBuilder:
    return ChunkedLabelBuilder(
        tmp_path, tmp_path / "sofa", tmp_path / "labels",
        rules_path=tmp_path / "rules.csv",
        infection_config_path=tmp_path / "infection.json",
        sepsis_config_path=tmp_path / "sepsis.json",
        shock_config_path=tmp_path / "shock.json",
    )


def _write_parquet(path: Path, frame: pd.DataFrame) -> None:
    connection = duckdb.connect()
    try:
        connection.register("frame", frame)
        connection.execute("COPY frame TO ? (FORMAT PARQUET)", [str(path)])
    finally:
        connection.close()


def test_admission_scoped_batch_read_does_not_multiply_source_events(tmp_path):
    _write_parquet(
        tmp_path / "prescriptions_cohort.parquet",
        pd.DataFrame({
            "subject_id": [1], "hadm_id": [10], "pharmacy_id": [1000],
        }),
    )
    connection = duckdb.connect()
    try:
        connection.register("_batch", pd.DataFrame({
            "subject_id": [1, 1], "hadm_id": [10, 10],
            "stay_id": [100, 101],
        }))
        result = _builder(tmp_path)._read_for_batch(
            connection, "prescriptions_cohort", scope="admission"
        )
    finally:
        connection.close()

    assert result.to_dict("records") == [
        {"subject_id": 1, "hadm_id": 10, "pharmacy_id": 1000}
    ]


def test_batch_read_rejects_unknown_source_scope(tmp_path):
    connection = duckdb.connect()
    try:
        with pytest.raises(ValueError, match="admission or stay"):
            _builder(tmp_path)._read_for_batch(
                connection, "unused", scope="patient"
            )
    finally:
        connection.close()
