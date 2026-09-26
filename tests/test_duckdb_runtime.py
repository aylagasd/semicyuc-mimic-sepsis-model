import duckdb
import pytest

from mimic_sepsis.duckdb_runtime import configure_duckdb, validate_duckdb_runtime


def test_duckdb_runtime_applies_memory_threads_and_temp_directory(tmp_path):
    connection = duckdb.connect()
    try:
        configure_duckdb(
            connection, memory_limit="1gb", temp_directory=tmp_path, threads=2
        )
        settings = dict(connection.execute(
            "SELECT name, value FROM duckdb_settings() "
            "WHERE name IN ('memory_limit', 'threads', 'temp_directory')"
        ).fetchall())
    finally:
        connection.close()

    assert settings["threads"] == "2"
    assert settings["temp_directory"] == str(tmp_path)
    assert float(settings["memory_limit"].split()[0]) <= 1024


@pytest.mark.parametrize(
    "memory_limit,threads",
    [("0GB", 2), ("8 GB", 2), ("8GB'; DROP TABLE x; --", 2), ("8GB", 0)],
)
def test_duckdb_runtime_rejects_unsafe_or_nonpositive_settings(
    memory_limit, threads
):
    with pytest.raises(ValueError):
        validate_duckdb_runtime(memory_limit, threads)
