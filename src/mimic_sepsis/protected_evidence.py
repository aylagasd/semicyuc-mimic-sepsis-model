"""Content-bound persistence for protected aggregate review evidence."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

from .artifacts import ArtifactValidationError


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )


def protected_evidence_sha256(content: Mapping[str, Any]) -> str:
    """Hash stable evidence independently of generation time and local path."""
    return hashlib.sha256(_canonical_json(content).encode("utf-8")).hexdigest()


def write_protected_evidence(
    path: str | Path, content: Mapping[str, Any]
) -> str:
    """Atomically persist protected aggregate evidence with mode ``0600``."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    digest = protected_evidence_sha256(content)
    document = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "report_sha256": digest,
        "content": content,
    }
    temporary = target.with_name(f".{target.name}.partial")
    try:
        temporary.write_text(
            json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return digest


def read_protected_evidence(path: str | Path) -> dict[str, Any]:
    """Read evidence and fail closed when its content digest does not match."""
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
        content = document["content"]
        expected = document["report_sha256"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise ArtifactValidationError("Malformed protected evidence report") from error
    if not isinstance(content, dict) or protected_evidence_sha256(content) != expected:
        raise ArtifactValidationError("Protected evidence checksum mismatch")
    return document
