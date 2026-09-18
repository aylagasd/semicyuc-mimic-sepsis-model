"""Content-level equivalence checks for two Parquet datasets."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import duckdb


@dataclass(frozen=True)
class EquivalenceResult:
    left_rows: int
    right_rows: int
    left_only: int
    right_only: int

    @property
    def equivalent(self) -> bool:
        return self.left_only == 0 and self.right_only == 0


def compare_parquet(left: str | Path, right: str | Path) -> EquivalenceResult:
    """Compare schemas and row multisets without returning patient-level data."""
    connection = duckdb.connect()
    try:
        left_path, right_path = str(left), str(right)
        left_schema = connection.execute(
            "DESCRIBE SELECT * FROM read_parquet(?)", [left_path]
        ).fetchall()
        right_schema = connection.execute(
            "DESCRIBE SELECT * FROM read_parquet(?)", [right_path]
        ).fetchall()
        if left_schema != right_schema:
            raise ValueError("Parquet schemas differ")
        query = """
            SELECT
              (SELECT count(*) FROM read_parquet(?)),
              (SELECT count(*) FROM read_parquet(?)),
              (SELECT count(*) FROM (
                 SELECT * FROM read_parquet(?)
                 EXCEPT ALL
                 SELECT * FROM read_parquet(?)
              )),
              (SELECT count(*) FROM (
                 SELECT * FROM read_parquet(?)
                 EXCEPT ALL
                 SELECT * FROM read_parquet(?)
              ))
        """
        values = connection.execute(
            query,
            [left_path, right_path, left_path, right_path, right_path, left_path],
        ).fetchone()
        return EquivalenceResult(*(int(value) for value in values))
    finally:
        connection.close()
