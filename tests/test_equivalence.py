import duckdb
import pandas as pd
import pytest

from mimic_sepsis.equivalence import compare_parquet


def _write(path, frame):
    connection = duckdb.connect()
    try:
        connection.register("frame", frame)
        connection.execute("COPY frame TO ? (FORMAT PARQUET)", [str(path)])
    finally:
        connection.close()


def test_comparison_uses_row_multisets_not_only_counts(tmp_path):
    left = tmp_path / "left.parquet"
    right = tmp_path / "right.parquet"
    _write(left, pd.DataFrame({"value": [1, 1, 2]}))
    _write(right, pd.DataFrame({"value": [1, 2, 2]}))
    result = compare_parquet(left, right)
    assert (result.left_rows, result.right_rows) == (3, 3)
    assert (result.left_only, result.right_only) == (1, 1)
    assert not result.equivalent


def test_comparison_rejects_schema_difference(tmp_path):
    left = tmp_path / "left.parquet"
    right = tmp_path / "right.parquet"
    _write(left, pd.DataFrame({"value": [1]}))
    _write(right, pd.DataFrame({"other": [1]}))
    with pytest.raises(ValueError, match="schemas differ"):
        compare_parquet(left, right)


def test_comparison_can_project_common_columns(tmp_path):
    left = tmp_path / "left.parquet"
    right = tmp_path / "right.parquet"
    _write(left, pd.DataFrame({"stay_id": [1, 2], "left_only": [3, 4]}))
    _write(right, pd.DataFrame({"stay_id": [1, 2], "right_only": [5, 6]}))
    result = compare_parquet(left, right, columns=("stay_id",))
    assert result.equivalent


def test_comparison_rejects_empty_projection(tmp_path):
    with pytest.raises(ValueError, match="cannot be empty"):
        compare_parquet(tmp_path / "left", tmp_path / "right", columns=())
