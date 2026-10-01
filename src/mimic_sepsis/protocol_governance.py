"""Cross-check the executable protocol gate and its human review documents."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Mapping


VALID_STATUSES = frozenset({"frozen", "provisional", "pending"})
DECISION_ROW = re.compile(
    r"^\|\s*(D\d{3})\s*\|\s*(frozen|provisional|pending)\s*\|",
    re.MULTILINE,
)
DOSSIER_ROW = re.compile(r"^\|\s*(D\d{3})\s*\|", re.MULTILINE)


@dataclass(frozen=True)
class GovernanceAudit:
    ready: bool
    decision_count: int
    open_decision_count: int
    dossier_decision_count: int
    issues: tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)


def _duplicates(values: list[str]) -> tuple[str, ...]:
    return tuple(sorted({value for value in values if values.count(value) > 1}))


def audit_protocol_governance(
    protocol: Mapping,
    decision_register_markdown: str,
    clinical_dossier_markdown: str,
) -> GovernanceAudit:
    """Fail closed when executable and narrative protocol states diverge."""
    issues: list[str] = []
    decisions = protocol.get("decisions")
    requirements = protocol.get("phase_requirements")
    if not isinstance(decisions, dict):
        decisions = {}
        issues.append("protocol:decisions_not_object")
    if not isinstance(requirements, dict):
        requirements = {}
        issues.append("protocol:phase_requirements_not_object")

    statuses: dict[str, str] = {}
    for decision, status in decisions.items():
        if not isinstance(decision, str) or not re.fullmatch(r"D\d{3}", decision):
            issues.append("protocol:invalid_decision_id")
            continue
        if status not in VALID_STATUSES:
            issues.append(f"{decision}:invalid_protocol_status")
            continue
        statuses[decision] = status

    register_rows = DECISION_ROW.findall(decision_register_markdown)
    register_ids = [decision for decision, _ in register_rows]
    for decision in _duplicates(register_ids):
        issues.append(f"{decision}:duplicate_register_row")
    register = dict(register_rows)

    dossier_ids = DOSSIER_ROW.findall(clinical_dossier_markdown)
    for decision in _duplicates(dossier_ids):
        issues.append(f"{decision}:duplicate_dossier_row")
    dossier = set(dossier_ids)

    for decision, status in sorted(statuses.items()):
        if decision not in register:
            issues.append(f"{decision}:missing_from_register")
        elif register[decision] != status:
            issues.append(f"{decision}:status_mismatch")

    open_register = {
        decision for decision, status in register.items() if status != "frozen"
    }
    protocol_ids = set(statuses)
    for decision in sorted(open_register - protocol_ids):
        issues.append(f"{decision}:open_but_missing_from_protocol")
    expected_dossier = {
        decision for decision, status in statuses.items() if status != "frozen"
    }
    for decision in sorted(expected_dossier - dossier):
        issues.append(f"{decision}:missing_from_dossier")
    for decision in sorted(dossier - expected_dossier):
        issues.append(f"{decision}:unexpected_in_dossier")

    phase_sets: dict[str, set[str]] = {}
    for phase in ("phenotype", "model", "test"):
        required = requirements.get(phase)
        if not isinstance(required, list) or not all(
            isinstance(item, str) for item in required
        ):
            issues.append(f"{phase}:invalid_requirements")
            phase_sets[phase] = set()
            continue
        for decision in _duplicates(required):
            issues.append(f"{phase}:{decision}:duplicate_requirement")
        phase_sets[phase] = set(required)
        for decision in sorted(phase_sets[phase] - protocol_ids):
            issues.append(f"{phase}:{decision}:unknown_requirement")
    if not phase_sets["phenotype"].issubset(phase_sets["model"]):
        issues.append("phases:phenotype_not_subset_of_model")
    if not phase_sets["model"].issubset(phase_sets["test"]):
        issues.append("phases:model_not_subset_of_test")

    unique_issues = tuple(sorted(set(issues)))
    return GovernanceAudit(
        ready=not unique_issues,
        decision_count=len(statuses),
        open_decision_count=len(expected_dossier),
        dossier_decision_count=len(dossier),
        issues=unique_issues,
    )
