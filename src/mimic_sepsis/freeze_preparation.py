"""Fail-closed preparation of a model-freeze document from aggregate evidence."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from .deployment import preflight_protocol_status
from .model_freeze import validate_model_freeze_document
from .report_artifacts import read_aggregate_report, read_report_config


@dataclass(frozen=True)
class ModelFreezePreparation:
    ready_to_freeze: bool
    blockers: tuple[str, ...]
    document: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def prepare_model_freeze_draft(
    report_root: str,
    protocol_status: Mapping[str, Any],
    *,
    code_commit: str,
    worktree_clean: bool,
    selection: Mapping[str, Any] | None = None,
    generated_at_utc: str | None = None,
) -> ModelFreezePreparation:
    """Build a non-authorizing draft and enumerate every unresolved blocker."""
    _, report = read_aggregate_report(report_root)
    report_config = read_report_config(report_root)
    modeling = report_config.get("modeling")
    if not isinstance(modeling, Mapping):
        raise ValueError("Report config lacks the modeling specification")
    source_run = str(report_config.get("source_run") or "").strip()
    if not source_run:
        raise ValueError("Report config lacks source_run")
    selection = {} if selection is None else dict(selection)
    generated = generated_at_utc or datetime.now(timezone.utc).isoformat()
    calibration = selection.get("calibration")
    if not isinstance(calibration, Mapping):
        calibration = {"method": None, "intercept": None, "slope": None}
    thresholds = selection.get("operating_thresholds")
    if not isinstance(thresholds, list):
        thresholds = []
    parameters = selection.get("model_parameters")
    if not isinstance(parameters, Mapping):
        parameters = {}
    primary_model = selection.get("primary_model")
    features = selection.get(
        "feature_columns", modeling.get("clinical_baseline_features", [])
    )
    document = {
        "calibration": dict(calibration),
        "code_commit": str(code_commit),
        "data_version": report.data_version,
        "decision_statuses": dict(protocol_status.get("decisions", {})),
        "feature_columns": list(features) if isinstance(features, list) else [],
        "frozen_at_utc": None,
        "generated_at_utc": generated,
        "horizon_hours": modeling.get("primary_horizon_hours"),
        "model_parameters": dict(parameters),
        "operating_thresholds": list(thresholds),
        "primary_model": primary_model,
        "primary_target": modeling.get("primary_target"),
        "schema_version": 1,
        "source_run_id": source_run,
        "status": "draft",
        "test_access": "locked_until_release",
        "validation_report_sha256": report.report_sha256,
    }
    blockers: list[str] = []
    if report.data_version == "2.2":
        blockers.append("demo_data_not_eligible_for_model_freeze")
    if not worktree_clean:
        blockers.append("git_worktree_not_clean")
    gate = preflight_protocol_status(protocol_status, "test")
    blockers.extend(f"protocol:{item}" for item in gate.blockers)
    if primary_model is None:
        blockers.append("primary_model_not_selected")
    if not parameters:
        blockers.append("model_parameters_not_frozen")
    if calibration.get("method") is None:
        blockers.append("calibration_not_frozen")
    if not thresholds:
        blockers.append("operating_thresholds_not_frozen")

    if not blockers:
        candidate = {
            **document,
            "status": "frozen",
            "frozen_at_utc": generated,
        }
        try:
            validate_model_freeze_document(candidate)
        except ValueError as error:
            blockers.append(f"invalid_selection:{error}")
    return ModelFreezePreparation(
        ready_to_freeze=not blockers,
        blockers=tuple(blockers),
        document=document,
    )
