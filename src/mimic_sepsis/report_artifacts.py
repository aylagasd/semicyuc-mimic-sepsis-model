"""Verifiable persistence for aggregate, patient-safe development reports."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from .artifacts import ArtifactStore, ArtifactValidationError
from .reporting import DevelopmentReport


FORBIDDEN_ROW_COLUMNS = frozenset({
    "subject_id", "hadm_id", "stay_id", "landmark_time", "event_time",
})
REPORT_TABLES = tuple(field.name for field in fields(DevelopmentReport))


@dataclass(frozen=True)
class AggregateReportManifest:
    schema_version: int
    data_version: str
    code_version: str
    config_sha256: str
    table_sha256: Mapping[str, str]
    report_sha256: str
    created_at_utc: str


def canonical_sha256(value: Mapping[str, Any]) -> str:
    """Hash JSON-compatible configuration using a stable representation."""
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def implementation_sha256(paths: Sequence[str | Path]) -> str:
    """Hash an ordered set of implementation files without exposing contents."""
    digest = hashlib.sha256()
    for path in sorted(Path(item) for item in paths):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _validate_aggregate_table(name: str, frame: pd.DataFrame) -> None:
    forbidden = sorted(FORBIDDEN_ROW_COLUMNS & set(frame.columns))
    if forbidden:
        raise ValueError(
            f"Aggregate report table {name!r} contains row identifiers: "
            + ", ".join(forbidden)
        )
    if "privacy_suppressed" in frame:
        suppressed = frame["privacy_suppressed"].fillna(False).astype(bool)
        protected = [
            column for column in (
                "landmarks", "patients", "stays", "events", "nonevents",
                "missing_landmarks", "observed_landmarks",
                "patients_with_missing", "patients_with_observed",
            ) if column in frame
        ]
        if protected and frame.loc[suppressed, protected].notna().any().any():
            raise ValueError(f"Suppressed counts remain visible in {name!r}")


def write_aggregate_report(
    report: DevelopmentReport,
    root: str | Path,
    *,
    data_version: str,
    code_version: str,
    config: Mapping[str, Any],
) -> AggregateReportManifest:
    """Persist only aggregate tables and publish a content-bound manifest."""
    root = Path(root)
    store = ArtifactStore(root)
    # Privacy/schema checks are a transaction precondition: a late failure must
    # not leave an apparently usable subset of the report on disk.
    for name in REPORT_TABLES:
        _validate_aggregate_table(name, getattr(report, name))
    table_hashes = {}
    for name in REPORT_TABLES:
        frame = getattr(report, name)
        manifest = store.write_dataframe(
            name, frame, data_version=data_version,
            code_version=code_version, config=config,
        )
        table_hashes[name] = manifest.sha256
    config_hash = canonical_sha256(config)
    report_hash = canonical_sha256({
        "schema_version": 1,
        "data_version": str(data_version),
        "code_version": str(code_version),
        "config_sha256": config_hash,
        "table_sha256": table_hashes,
    })
    manifest = AggregateReportManifest(
        schema_version=1,
        data_version=str(data_version),
        code_version=str(code_version),
        config_sha256=config_hash,
        table_sha256=table_hashes,
        report_sha256=report_hash,
        created_at_utc=datetime.now(timezone.utc).isoformat(),
    )
    root.mkdir(parents=True, exist_ok=True)
    temporary = root / ".aggregate_report.partial.json"
    target = root / "aggregate_report.manifest.json"
    temporary.write_text(
        json.dumps(asdict(manifest), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, target)
    return manifest


def read_aggregate_report(
    root: str | Path,
    *,
    expected_config: Mapping[str, Any],
) -> tuple[DevelopmentReport, AggregateReportManifest]:
    """Validate and load a persisted aggregate report without patient rows."""
    root = Path(root)
    try:
        value = json.loads(
            (root / "aggregate_report.manifest.json").read_text(encoding="utf-8")
        )
        manifest = AggregateReportManifest(**value)
    except (FileNotFoundError, json.JSONDecodeError, TypeError) as error:
        raise ArtifactValidationError("Malformed aggregate report manifest") from error
    if manifest.schema_version != 1:
        raise ArtifactValidationError("Unsupported aggregate report schema")
    config_hash = canonical_sha256(expected_config)
    if manifest.config_sha256 != config_hash:
        raise ArtifactValidationError("Aggregate report configuration mismatch")
    store = ArtifactStore(root)
    tables = {}
    for name in REPORT_TABLES:
        artifact = store.validate(name, expected_config=expected_config)
        if manifest.table_sha256.get(name) != artifact.sha256:
            raise ArtifactValidationError("Aggregate report table hash mismatch")
        frame = store.read_dataframe(
            name, validate=False, expected_config=expected_config
        )
        _validate_aggregate_table(name, frame)
        tables[name] = frame
    expected_report_hash = canonical_sha256({
        "schema_version": manifest.schema_version,
        "data_version": manifest.data_version,
        "code_version": manifest.code_version,
        "config_sha256": manifest.config_sha256,
        "table_sha256": dict(manifest.table_sha256),
    })
    if manifest.report_sha256 != expected_report_hash:
        raise ArtifactValidationError("Aggregate report checksum mismatch")
    return DevelopmentReport(**tables), manifest
