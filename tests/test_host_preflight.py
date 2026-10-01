import pytest

from mimic_sepsis.host_preflight import GIB, audit_compute_host


PROFILE = {
    "schema_version": 1,
    "target_ram_gib": 32,
    "maximum_ram_fraction": 0.75,
    "maximum_parallel_workers": 2,
}


def _audit(**overrides):
    values = {
        "total_memory_bytes": 31 * GIB,
        "available_memory_bytes": 28 * GIB,
        "logical_cpu_count": 4,
        "work_free_bytes": 500 * GIB,
        "temp_free_bytes": 300 * GIB,
        "work_writable": True,
        "temp_writable": True,
        "shared_work_temp_filesystem": False,
        "minimum_work_free_gib": 250,
        "minimum_temp_free_gib": 200,
    }
    values.update(overrides)
    return audit_compute_host(PROFILE, **values)


def test_host_meeting_budget_and_disk_reserves_is_ready():
    report = _audit()
    assert report.ready
    assert report.blockers == ()
    assert report.target_budget_bytes == 24 * GIB
    assert not report.shared_work_temp_filesystem


def test_host_reports_all_capacity_blockers_without_clinical_values():
    report = _audit(
        total_memory_bytes=16 * GIB,
        available_memory_bytes=None,
        logical_cpu_count=1,
        work_free_bytes=100 * GIB,
        temp_free_bytes=100 * GIB,
        work_writable=False,
        temp_writable=False,
    )
    assert not report.ready
    assert set(report.blockers) == {
        "memory:total_below_budget",
        "memory:available_unavailable",
        "cpu:workers_unavailable",
        "work:path_not_writable",
        "temp:path_not_writable",
        "work:free_disk_below_minimum",
        "temp:free_disk_below_minimum",
    }
    assert "subject_id" not in report.to_dict()


def test_shared_filesystem_requires_combined_disk_reserve():
    report = _audit(
        shared_work_temp_filesystem=True,
        work_free_bytes=300 * GIB,
        temp_free_bytes=300 * GIB,
    )
    assert not report.ready
    assert "shared:free_disk_below_combined_minimum" in report.blockers


@pytest.mark.parametrize(
    "profile",
    [
        {**PROFILE, "schema_version": 2},
        {**PROFILE, "maximum_ram_fraction": 1},
        {**PROFILE, "maximum_parallel_workers": 0},
    ],
)
def test_host_audit_rejects_invalid_profiles(profile):
    with pytest.raises(ValueError):
        audit_compute_host(
            profile,
            total_memory_bytes=32 * GIB,
            available_memory_bytes=30 * GIB,
            logical_cpu_count=4,
            work_free_bytes=GIB,
            temp_free_bytes=GIB,
            work_writable=True,
            temp_writable=True,
            shared_work_temp_filesystem=True,
        )


def test_host_audit_rejects_negative_disk_requirement():
    with pytest.raises(ValueError, match="non-negative"):
        _audit(minimum_work_free_gib=-1)
