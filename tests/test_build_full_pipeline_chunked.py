from pathlib import Path

from scripts.build_full_pipeline_chunked import (
    fully_materialized_report, select_resource_report_path,
)


def test_first_resume_keeps_canonical_report_path_when_none_exists(tmp_path):
    canonical = tmp_path / "resource_report.json"
    assert select_resource_report_path(canonical, resume=True) == canonical


def test_later_resume_uses_separate_report_path(tmp_path):
    canonical = tmp_path / "resource_report.json"
    canonical.write_text("{}", encoding="utf-8")
    assert select_resource_report_path(canonical, resume=True) == (
        tmp_path / "resource_report.resume.json"
    )
    assert select_resource_report_path(canonical, resume=False) == canonical


def test_only_fresh_complete_stage_set_is_a_full_materialization():
    stages = [
        {"output_bytes": 100, "output_bytes_added": 100}
        for _ in range(4)
    ]
    assert fully_materialized_report(stages)
    stages[2]["output_bytes_added"] = 0
    assert not fully_materialized_report(stages)
    stages[2]["output_bytes_added"] = 50
    assert not fully_materialized_report(stages)
