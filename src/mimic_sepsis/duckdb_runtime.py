"""Shared bounded-resource configuration for local DuckDB connections."""

from __future__ import annotations

from pathlib import Path
import re

import duckdb


_STORAGE_SIZE = re.compile(r"[1-9][0-9]*(?:KB|MB|GB|TB)")


def validate_duckdb_runtime(memory_limit: str, threads: int) -> tuple[str, int]:
    """Validate settings before interpolating them into DuckDB ``SET`` calls."""
    normalized_limit = str(memory_limit).upper()
    if not _STORAGE_SIZE.fullmatch(normalized_limit):
        raise ValueError("duckdb memory limit must be a positive storage size")
    normalized_threads = int(threads)
    if normalized_threads <= 0:
        raise ValueError("duckdb threads must be positive")
    return normalized_limit, normalized_threads


def configure_duckdb(
    connection: duckdb.DuckDBPyConnection,
    *,
    memory_limit: str,
    temp_directory: str | Path,
    threads: int,
) -> None:
    """Apply one validated memory, spill-directory and thread budget."""
    normalized_limit, normalized_threads = validate_duckdb_runtime(
        memory_limit, threads
    )
    temporary = Path(temp_directory)
    temporary.mkdir(parents=True, exist_ok=True)
    connection.execute(f"SET memory_limit='{normalized_limit}'")
    connection.execute(f"SET threads={normalized_threads}")
    connection.execute("SET temp_directory=?", [str(temporary)])
