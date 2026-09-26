import hashlib
import json
import sys

from scripts import validate_pipeline_resources


def test_resource_validator_cli_reports_only_aggregate_decision(
    tmp_path, monkeypatch, capsys
):
    profile = {
        "schema_version": 1,
        "chunk_batch_size": 100,
        "duckdb_memory_limit": "8GB",
        "maximum_parallel_workers": 2,
        "maximum_ram_fraction": 0.75,
        "target_ram_gib": 32,
    }
    profile_path = tmp_path / "compute.json"
    profile_path.write_text(json.dumps(profile), encoding="utf-8")
    profile_sha = hashlib.sha256(profile_path.read_bytes()).hexdigest()
    payload = {
        "schema_version": 1,
        "completed": True,
        "error_type": None,
        "compute_profile_sha256": profile_sha,
        "runtime": {
            "batch_size": 100,
            "duckdb_memory_limit": "8GB",
            "duckdb_threads": 2,
            "resume": False,
        },
        "stages": [
            {
                "stage": name,
                "status": "completed",
                "error_type": None,
                "rows": 10,
                "parts": 2,
                "peak_rss_bytes": 1024**3,
                "peak_swap_bytes": 0,
            }
            for name in ("sofa", "labels", "landmarks", "features")
        ],
    }
    report_path = tmp_path / "resources.json"
    report_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [
        "validate_pipeline_resources.py", str(report_path),
        "--compute-profile", str(profile_path),
    ])

    assert validate_pipeline_resources.main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["ready"] is True
    assert output["peak_swap_bytes"] == 0
    assert "subject_id" not in json.dumps(output)


def test_resource_validator_cli_fails_closed_for_missing_report(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(sys, "argv", [
        "validate_pipeline_resources.py", str(tmp_path / "missing.json")
    ])
    assert validate_pipeline_resources.main() == 2
    output = json.loads(capsys.readouterr().out)
    assert output["ready"] is False
    assert str(tmp_path) not in json.dumps(output)
