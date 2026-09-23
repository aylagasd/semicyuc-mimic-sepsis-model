"""Validation of an explicit, local authorization to materialize locked test data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from .model_freeze import validate_model_freeze


REQUIRED_APPROVER_ROLES = frozenset({"clinical_lead", "statistical_lead"})


@dataclass(frozen=True)
class TestRelease:
    data_version: str
    approved_at_utc: str
    approver_roles: tuple[str, ...]
    model_freeze_sha256: str
    reason: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_test_release(
    release_path: str | Path,
    model_freeze_path: str | Path,
    *,
    expected_data_version: str,
) -> TestRelease:
    """Require two-role approval bound to a frozen model file and data version."""
    release_path = Path(release_path)
    model_freeze_path = Path(model_freeze_path)
    release = json.loads(release_path.read_text(encoding="utf-8"))
    validate_model_freeze(model_freeze_path)
    if release.get("schema_version") != 1:
        raise ValueError("Unsupported test-release schema_version")
    if release.get("approval_status") != "approved":
        raise ValueError("Test release is not approved")
    if release.get("data_version") != str(expected_data_version):
        raise ValueError("Test release data_version does not match the extract")
    roles = tuple(sorted(set(release.get("approver_roles", ()))))
    if not REQUIRED_APPROVER_ROLES.issubset(roles):
        raise ValueError("Test release requires clinical and statistical approvers")
    timestamp = str(release.get("approved_at_utc", ""))
    try:
        approved_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("approved_at_utc must be an ISO-8601 timestamp") from error
    if approved_at.tzinfo is None or approved_at.utcoffset() != timezone.utc.utcoffset(None):
        raise ValueError("approved_at_utc must include a UTC offset")
    expected_hash = _sha256(model_freeze_path)
    supplied_hash = str(release.get("model_freeze_sha256", ""))
    if supplied_hash != expected_hash:
        raise ValueError("Test release is not bound to this model freeze")
    reason = str(release.get("reason", "")).strip()
    if len(reason) < 20:
        raise ValueError("Test release reason must be explicit")
    return TestRelease(
        data_version=str(expected_data_version),
        approved_at_utc=timestamp,
        approver_roles=roles,
        model_freeze_sha256=expected_hash,
        reason=reason,
    )
