"""Build a content-bound aggregate dossier for phenotype freeze review.

The report contains unsuppressed aggregate counts and therefore belongs in the
protected derived-data area, even though it contains no row identifiers.  It is
evidence for human review; it cannot mutate protocol status.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from .artifacts import ArtifactStore, ArtifactValidationError
from .chunked_labels import LABEL_ARTIFACTS
from .chunked_sofa import (
    partitioned_dataset_sha256,
    read_partitioned_dataset,
    validate_partitioned_dataset,
)
from .phenotype_audit import (
    coverage_sensitivity_summary,
    coverage_summary,
    decision_evidence_summary,
    infection_timing_summary,
    pair_multiplicity,
    phenotype_summary,
    shock_proxy_summary,
    sofa_completeness_summary,
)


REPORT_TABLES = (
    "phenotype_summary",
    "infection_timing",
    "pair_multiplicity",
    "coverage",
    "coverage_sensitivities",
    "sofa_completeness_at_t0",
    "shock_proxy",
    "decision_evidence",
)
FORBIDDEN_REPORT_COLUMNS = frozenset({
    "subject_id", "hadm_id", "stay_id", "antibiotic_id", "culture_id",
})


@dataclass(frozen=True)
class ValidatedPhenotypeSource:
    """Validated patient-level inputs plus non-sensitive source provenance."""

    layout: str
    data_version: str
    config_sha256: str
    artifact_sha256: Mapping[str, str]
    tables: Mapping[str, pd.DataFrame]


def _same(values: list[str], field: str) -> str:
    unique = set(values)
    if len(unique) != 1:
        raise ArtifactValidationError(f"Label artifacts disagree on {field}")
    return unique.pop()


def _demo_label_directory(path: Path) -> Path | None:
    direct = path if path.name == "40_labels" else path / "40_labels"
    expected = direct / "sepsis_episodes.manifest.json"
    return direct if expected.is_file() else None


def load_validated_phenotype_source(path: str | Path) -> ValidatedPhenotypeSource:
    """Load either a demo run or a partitioned full-pipeline label run."""
    root = Path(path)
    demo = _demo_label_directory(root)
    if demo is not None:
        store = ArtifactStore(demo)
        manifests = {name: store.validate(name) for name in LABEL_ARTIFACTS}
        data_version = _same(
            [item.data_version for item in manifests.values()], "data_version"
        )
        config_sha256 = _same(
            [item.config_sha256 for item in manifests.values()], "config_sha256"
        )
        tables = {
            name: store.read_dataframe(name, validate=False)
            for name in LABEL_ARTIFACTS
        }
        return ValidatedPhenotypeSource(
            layout="demo_artifact_store",
            data_version=data_version,
            config_sha256=config_sha256,
            artifact_sha256={name: item.sha256 for name, item in manifests.items()},
            tables=tables,
        )

    if all((root / name / f"{name}.dataset.json").is_file() for name in LABEL_ARTIFACTS):
        manifests = {
            name: validate_partitioned_dataset(root / name, name)
            for name in LABEL_ARTIFACTS
        }
        data_version = _same(
            [item.data_version for item in manifests.values()], "data_version"
        )
        config_sha256 = _same(
            [item.config_sha256 for item in manifests.values()], "config_sha256"
        )
        tables = {
            name: read_partitioned_dataset(
                root / name, name, validated_manifest=manifests[name]
            )
            for name in LABEL_ARTIFACTS
        }
        return ValidatedPhenotypeSource(
            layout="partitioned_label_run",
            data_version=data_version,
            config_sha256=config_sha256,
            artifact_sha256={
                name: partitioned_dataset_sha256(item)
                for name, item in manifests.items()
            },
            tables=tables,
        )

    raise ArtifactValidationError(
        "Path is neither a complete demo run nor a partitioned label run"
    )


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    forbidden = FORBIDDEN_REPORT_COLUMNS & set(frame.columns)
    if forbidden:
        raise ValueError(
            "Phenotype evidence contains row identifiers: "
            + ", ".join(sorted(forbidden))
        )
    clean = frame.astype(object).where(pd.notna(frame), None)
    return clean.to_dict(orient="records")


def build_phenotype_evidence(
    source: ValidatedPhenotypeSource,
    *,
    protocol_status: Mapping[str, str],
) -> dict[str, Any]:
    """Return the stable, timestamp-free content of a freeze-review report."""
    pairs = source.tables["suspected_infection_pairs"]
    episodes = source.tables["sepsis_episodes"]
    sepsis_stays = source.tables["sepsis_stays"]
    shock_stays = source.tables["septic_shock_stays"]
    decisions = decision_evidence_summary().copy()
    decisions["current_status"] = decisions["decision_id"].map(protocol_status)
    if decisions["current_status"].isna().any():
        missing = decisions.loc[
            decisions["current_status"].isna(), "decision_id"
        ].tolist()
        raise ValueError("Protocol status is missing decisions: " + ", ".join(missing))

    frames = {
        "phenotype_summary": phenotype_summary(
            pairs, episodes, sepsis_stays, shock_stays
        ),
        "infection_timing": infection_timing_summary(pairs),
        "pair_multiplicity": pair_multiplicity(pairs),
        "coverage": coverage_summary(episodes),
        "coverage_sensitivities": coverage_sensitivity_summary(episodes),
        "sofa_completeness_at_t0": sofa_completeness_summary(sepsis_stays),
        "shock_proxy": shock_proxy_summary(shock_stays),
        "decision_evidence": decisions,
    }
    if tuple(frames) != REPORT_TABLES:
        raise RuntimeError("Internal phenotype report table order changed")
    return {
        "schema_version": 1,
        "purpose": "protocol_freeze_review_only",
        "distribution_class": "protected_aggregate_unsuppressed_counts",
        "clinical_status_mutated": False,
        "source": {
            "layout": source.layout,
            "data_version": source.data_version,
            "config_sha256": source.config_sha256,
            "artifact_sha256": dict(source.artifact_sha256),
        },
        "definitions": {
            "D002": "not comparable within one cohort-policy run",
            "D004": "first qualifying EMAR administration plus blood culture",
            "D010": "EHR shock proxy; adequate fluids are not inferred",
            "D011": (
                "coverage sensitivities plus descriptive primary-t0 missingness; "
                "six-component sensitivity still requires hourly recomputation"
            ),
        },
        "tables": {name: _records(frame) for name, frame in frames.items()},
    }


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )


def evidence_sha256(content: Mapping[str, Any]) -> str:
    """Hash stable report content independently of generation time and path."""
    return hashlib.sha256(_canonical_json(content).encode("utf-8")).hexdigest()


def write_phenotype_evidence(
    path: str | Path, content: Mapping[str, Any]
) -> str:
    """Atomically persist protected aggregate evidence with restrictive mode."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    digest = evidence_sha256(content)
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


def read_phenotype_evidence(path: str | Path) -> dict[str, Any]:
    """Read a report and fail closed when its content digest does not match."""
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
        content = document["content"]
        expected = document["report_sha256"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise ArtifactValidationError("Malformed phenotype evidence report") from error
    if not isinstance(content, dict) or evidence_sha256(content) != expected:
        raise ArtifactValidationError("Phenotype evidence checksum mismatch")
    return document
