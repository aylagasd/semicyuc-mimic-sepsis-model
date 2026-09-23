"""Executable validation contract for a model specification frozen before test."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping


REQUIRED_FROZEN_DECISIONS = frozenset({
    "D002", "D004", "D010", "D011", "D014", "D016", "D027", "D029",
    "D031",
})
ALLOWED_MODELS = frozenset({"logistic", "gradient_boosting"})
ALLOWED_CALIBRATION = frozenset({"none", "logistic_intercept_and_slope"})
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{7,40}$")


@dataclass(frozen=True)
class FrozenModelSpecification:
    data_version: str
    source_run_id: str
    code_commit: str
    primary_target: str
    horizon_hours: int
    feature_columns: tuple[str, ...]
    primary_model: str
    model_parameters: Mapping[str, Any]
    calibration: Mapping[str, Any]
    operating_thresholds: tuple[float, ...]
    validation_report_sha256: str


def _utc_timestamp(value: object, field: str) -> str:
    text = str(value or "")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{field} must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(None):
        raise ValueError(f"{field} must include a UTC offset")
    return text


def validate_model_freeze_document(value: Mapping[str, Any]) -> FrozenModelSpecification:
    """Validate that every test-sensitive choice has a concrete frozen value."""
    if value.get("schema_version") != 1:
        raise ValueError("Unsupported model-freeze schema_version")
    if value.get("status") != "frozen":
        raise ValueError("Model specification is not frozen")
    if value.get("test_access") != "locked_until_release":
        raise ValueError("Model freeze lacks locked test-access status")
    _utc_timestamp(value.get("frozen_at_utc"), "frozen_at_utc")
    data_version = str(value.get("data_version") or "").strip()
    source_run_id = str(value.get("source_run_id") or "").strip()
    if not data_version or not source_run_id:
        raise ValueError("data_version and source_run_id must be frozen")
    code_commit = str(value.get("code_commit") or "")
    if not COMMIT_PATTERN.fullmatch(code_commit):
        raise ValueError("code_commit must be a Git commit hash")
    primary_target = str(value.get("primary_target") or "")
    if primary_target not in {"sepsis3", "septic_shock"}:
        raise ValueError("primary_target is invalid")
    horizon_hours = value.get("horizon_hours")
    if not isinstance(horizon_hours, int) or horizon_hours <= 0:
        raise ValueError("horizon_hours must be a positive integer")
    features = tuple(value.get("feature_columns") or ())
    if (
        not features or len(features) != len(set(features))
        or not all(isinstance(item, str) and item for item in features)
    ):
        raise ValueError("feature_columns must be non-empty and unique")
    primary_model = str(value.get("primary_model") or "")
    if primary_model not in ALLOWED_MODELS:
        raise ValueError("primary_model is not supported")
    parameters = value.get("model_parameters")
    if not isinstance(parameters, dict) or not parameters:
        raise ValueError("model_parameters must be a non-empty object")
    calibration = value.get("calibration")
    if not isinstance(calibration, dict):
        raise ValueError("calibration must be an object")
    method = calibration.get("method")
    if method not in ALLOWED_CALIBRATION:
        raise ValueError("calibration method is invalid")
    if method == "logistic_intercept_and_slope":
        for field in ("intercept", "slope"):
            number = calibration.get(field)
            if not isinstance(number, (int, float)) or not math.isfinite(number):
                raise ValueError(f"calibration {field} must be finite")
    thresholds = value.get("operating_thresholds")
    if not isinstance(thresholds, list) or not thresholds:
        raise ValueError("operating_thresholds must contain at least one value")
    if (
        len(thresholds) != len(set(thresholds))
        or any(not isinstance(item, (int, float)) or not 0 < item < 1 for item in thresholds)
    ):
        raise ValueError("operating_thresholds must be unique probabilities")
    decisions = value.get("decision_statuses")
    if not isinstance(decisions, dict):
        raise ValueError("decision_statuses must be an object")
    unresolved = sorted(
        decision for decision in REQUIRED_FROZEN_DECISIONS
        if decisions.get(decision) != "frozen"
    )
    if unresolved:
        raise ValueError(f"Unfrozen model decisions: {', '.join(unresolved)}")
    validation_hash = str(value.get("validation_report_sha256") or "")
    if not SHA256_PATTERN.fullmatch(validation_hash):
        raise ValueError("validation_report_sha256 must be a SHA-256 digest")
    return FrozenModelSpecification(
        data_version=data_version,
        source_run_id=source_run_id,
        code_commit=code_commit,
        primary_target=primary_target,
        horizon_hours=horizon_hours,
        feature_columns=features,
        primary_model=primary_model,
        model_parameters=parameters,
        calibration=calibration,
        operating_thresholds=tuple(float(item) for item in thresholds),
        validation_report_sha256=validation_hash,
    )


def validate_model_freeze(path: str | Path) -> FrozenModelSpecification:
    """Read and validate a versioned model-freeze JSON document."""
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    return validate_model_freeze_document(value)
