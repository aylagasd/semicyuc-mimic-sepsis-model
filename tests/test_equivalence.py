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
