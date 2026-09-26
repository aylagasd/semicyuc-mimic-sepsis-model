import json

from mimic_sepsis.resource_telemetry import (
    StageResourceMonitor, directory_bytes, write_resource_report,
)


def test_stage_resource_monitor_records_only_aggregate_counters(tmp_path):
    output = tmp_path / "stage"
    with StageResourceMonitor("features", output, sample_interval_seconds=0.001) as monitor:
        output.mkdir()
        (output / "part.parquet").write_bytes(b"safe-aggregate-test")
        monitor.set_counts(rows=12, parts=3)

    result = monitor.measurement.to_dict()
    assert result["stage"] == "features"
    assert result["status"] == "completed"
    assert result["rows"] == 12
    assert result["parts"] == 3
    assert result["output_bytes"] == len(b"safe-aggregate-test")
    assert result["elapsed_seconds"] >= 0
    assert result["peak_swap_bytes"] is not None
    assert result["peak_swap_bytes"] >= 0
    assert "error_message" not in result


def test_failed_stage_records_exception_type_without_message(tmp_path):
    try:
        with StageResourceMonitor("labels", tmp_path) as monitor:
            raise RuntimeError("a private path or value must not be persisted")
    except RuntimeError:
        pass

    result = monitor.measurement.to_dict()
    assert result["status"] == "failed"
    assert result["error_type"] == "RuntimeError"
    assert "private" not in json.dumps(result)


def test_resource_report_is_atomic_and_directory_size_uses_files(tmp_path):
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "a").write_bytes(b"123")
    (nested / "b").write_bytes(b"4567")
    assert directory_bytes(nested) == 7

    report = tmp_path / "resource_report.json"
    write_resource_report(report, {"schema_version": 1, "completed": True})
    assert json.loads(report.read_text(encoding="utf-8"))["completed"]
    assert not report.with_suffix(".json.partial").exists()
