import pandas as pd

from mimic_sepsis.freeze_preparation import prepare_model_freeze_draft
from mimic_sepsis.report_artifacts import REPORT_TABLES, write_aggregate_report
from mimic_sepsis.reporting import DevelopmentReport


def _report(root, *, data_version="3.1"):
    report = DevelopmentReport(**{
        name: pd.DataFrame({"metric": [name], "estimate": [0.5]})
        for name in REPORT_TABLES
    })
    config = {
        "source_run": "full-run-123",
        "modeling": {
            "clinical_baseline_features": ["heart_rate_last_24h"],
            "primary_horizon_hours": 6,
            "primary_target": "sepsis3",
        },
    }
    return write_aggregate_report(
        report, root, data_version=data_version,
        code_version="abc1234", config=config,
    )


def _protocol(status="frozen"):
    decisions = {
        key: status for key in (
            "D002", "D004", "D010", "D011", "D014", "D016", "D027",
            "D029", "D031",
        )
    }
    return {"decisions": decisions, "phase_requirements": {"test": list(decisions)}}


def _selection():
    return {
        "primary_model": "logistic",
        "model_parameters": {"C": 1.0},
        "calibration": {"method": "none", "intercept": None, "slope": None},
        "operating_thresholds": [0.05],
    }


def test_complete_full_data_draft_can_be_ready_but_never_self_authorizes(tmp_path):
    report = _report(tmp_path)
    result = prepare_model_freeze_draft(
        str(tmp_path), _protocol(), code_commit="abcdef1234567890",
        worktree_clean=True, selection=_selection(),
        generated_at_utc="2026-09-23T12:00:00Z",
    )
    assert result.ready_to_freeze
    assert not result.blockers
    assert result.document["status"] == "draft"
    assert result.document["frozen_at_utc"] is None
    assert result.document["validation_report_sha256"] == report.report_sha256


def test_demo_and_missing_human_choices_remain_blocked(tmp_path):
    _report(tmp_path, data_version="2.2")
    result = prepare_model_freeze_draft(
        str(tmp_path), _protocol("provisional"), code_commit="abcdef1234567890",
        worktree_clean=False,
    )
    assert not result.ready_to_freeze
    assert "demo_data_not_eligible_for_model_freeze" in result.blockers
    assert "git_worktree_not_clean" in result.blockers
    assert "primary_model_not_selected" in result.blockers
    assert any(item.startswith("protocol:D002:") for item in result.blockers)


def test_invalid_complete_selection_is_reported_as_blocker(tmp_path):
    _report(tmp_path)
    selection = _selection()
    selection["operating_thresholds"] = [2.0]
    result = prepare_model_freeze_draft(
        str(tmp_path), _protocol(), code_commit="abcdef1234567890",
        worktree_clean=True, selection=selection,
        generated_at_utc="2026-09-23T12:00:00Z",
    )
    assert not result.ready_to_freeze
    assert result.blockers[0].startswith("invalid_selection:")
