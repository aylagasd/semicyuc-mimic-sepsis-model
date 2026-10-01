import copy

import pytest

from mimic_sepsis.resource_validation import audit_pipeline_resources


PROFILE = {
    "schema_version": 1,
    "chunk_batch_size": 100,
    "duckdb_memory_limit": "8GB",
    "maximum_parallel_workers": 2,
    "maximum_ram_fraction": 0.75,
    "target_ram_gib": 32,
}


def _payload():
    return {
        "schema_version": 1,
        "completed": True,
        "error_type": None,
        "compute_profile_sha256": "profile-sha",
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
                "rows": 1,
                "parts": 1,
                "output_bytes": 1024,
                "output_bytes_added": 1024,
                "peak_rss_bytes": 2 * 1024**3,
                "peak_swap_bytes": 0,
            }
            for name in ("sofa", "labels", "landmarks", "features")
        ],
    }


def _audit(payload):
    return audit_pipeline_resources(
        payload, PROFILE, expected_compute_profile_sha256="profile-sha"
    )


def test_complete_resource_report_within_profile_is_ready():
    result = _audit(_payload())
    assert result.ready
    assert result.blockers == ()
    assert result.peak_swap_bytes == 0
    assert result.target_budget_bytes == 24 * 1024**3


@pytest.mark.parametrize(
    "mutate,blocker",
    [
        (lambda value: value.update(completed=False), "pipeline:not_completed"),
        (
            lambda value: value["runtime"].update(duckdb_threads=4),
            "runtime:profile_mismatch",
        ),
        (
            lambda value: value["stages"][3].update(peak_swap_bytes=4096),
            "memory:swap_observed",
        ),
        (
            lambda value: value["stages"][0].update(peak_rss_bytes=25 * 1024**3),
            "memory:rss_budget_exceeded",
        ),
        (
            lambda value: value["stages"].reverse(),
            "stages:unexpected_sequence",
        ),
    ],
)
def test_resource_gate_fails_closed_for_operational_blockers(mutate, blocker):
    payload = copy.deepcopy(_payload())
    mutate(payload)
    result = _audit(payload)
    assert not result.ready
    assert blocker in result.blockers


def test_resource_gate_rejects_missing_aggregate_counts():
    payload = _payload()
    del payload["stages"][0]["rows"]
    with pytest.raises(ValueError, match="aggregate counts"):
        _audit(payload)


def test_resource_gate_rejects_resume_without_stage_materialization():
    payload = _payload()
    payload["runtime"]["resume"] = True
    for stage in payload["stages"]:
        stage["output_bytes_added"] = 0
    result = _audit(payload)

    assert not result.ready
    assert not result.all_stages_materialized
    assert "stage:sofa:no_materialization" in result.blockers


def test_resource_gate_requires_materialization_counts():
    payload = _payload()
    del payload["stages"][0]["output_bytes_added"]
    with pytest.raises(ValueError, match="materialization counts"):
        _audit(payload)


def test_resource_gate_rejects_partial_resume_measurement():
    payload = _payload()
    payload["runtime"]["resume"] = True
    payload["stages"][1]["output_bytes"] = 2048
    result = _audit(payload)

    assert not result.ready
    assert "stage:labels:no_materialization" in result.blockers
