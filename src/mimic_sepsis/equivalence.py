"""Content-level equivalence checks for two Parquet datasets."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from collections.abc import Sequence

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


def compare_parquet(
    left: str | Path,
    right: str | Path,
    *,
    columns: Sequence[str] | None = None,
) -> EquivalenceResult:
    """Compare projected schemas and row multisets without returning row data."""
    if columns is not None and not columns:
        raise ValueError("columns cannot be empty")
    projection = "*" if columns is None else ", ".join(
        f'"{column.replace(chr(34), chr(34) * 2)}"' for column in columns
    )
    connection = duckdb.connect()
    try:
        left_path, right_path = str(left), str(right)
        left_schema = connection.execute(
            f"DESCRIBE SELECT {projection} FROM read_parquet(?)", [left_path]
        ).fetchall()
        right_schema = connection.execute(
            f"DESCRIBE SELECT {projection} FROM read_parquet(?)", [right_path]
        ).fetchall()
        if left_schema != right_schema:
            raise ValueError("Parquet schemas differ")
        query = """
            SELECT
              (SELECT count(*) FROM (SELECT {projection} FROM read_parquet(?))),
              (SELECT count(*) FROM (SELECT {projection} FROM read_parquet(?))),
              (SELECT count(*) FROM (
                 SELECT {projection} FROM read_parquet(?)
                 EXCEPT ALL
                 SELECT {projection} FROM read_parquet(?)
              )),
              (SELECT count(*) FROM (
                 SELECT {projection} FROM read_parquet(?)
                 EXCEPT ALL
                 SELECT {projection} FROM read_parquet(?)
              ))
        """.format(projection=projection)
        values = connection.execute(
            query,
            [left_path, right_path, left_path, right_path, right_path, left_path],
        ).fetchone()
        return EquivalenceResult(*(int(value) for value in values))
    finally:
        connection.close()
