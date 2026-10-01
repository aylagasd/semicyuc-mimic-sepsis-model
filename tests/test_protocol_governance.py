import json
from pathlib import Path

from mimic_sepsis.protocol_governance import audit_protocol_governance


ROOT = Path(__file__).resolve().parents[1]


def _protocol():
    return {
        "decisions": {
            "D002": "provisional",
            "D004": "pending",
            "D031": "frozen",
        },
        "phase_requirements": {
            "phenotype": ["D002"],
            "model": ["D002", "D004"],
            "test": ["D002", "D004", "D031"],
        },
    }


def _register():
    return "\n".join((
        "| ID | Estado | Decisión |",
        "|---|---|---|",
        "| D002 | provisional | cohort |",
        "| D004 | pending | infection |",
        "| D031 | frozen | report |",
    ))


def _dossier():
    return "\n".join((
        "| ID | Propuesta |",
        "|---|---|",
        "| D002 | cohort |",
        "| D004 | infection |",
    ))


def test_governance_audit_accepts_aligned_documents():
    audit = audit_protocol_governance(_protocol(), _register(), _dossier())
    assert audit.ready
    assert audit.open_decision_count == 2
    assert audit.dossier_decision_count == 2


def test_governance_audit_reports_status_dossier_and_phase_drift():
    protocol = _protocol()
    protocol["decisions"]["D002"] = "frozen"
    protocol["phase_requirements"]["phenotype"] = ["D999"]
    audit = audit_protocol_governance(protocol, _register(), _dossier())
    assert not audit.ready
    assert "D002:status_mismatch" in audit.issues
    assert "D002:unexpected_in_dossier" in audit.issues
    assert "phenotype:D999:unknown_requirement" in audit.issues
    assert "phases:phenotype_not_subset_of_model" in audit.issues


def test_repository_protocol_governance_is_consistent():
    protocol = json.loads(
        (ROOT / "config" / "protocol_status.json").read_text(encoding="utf-8")
    )
    audit = audit_protocol_governance(
        protocol,
        (ROOT / "docs" / "decision_register.md").read_text(encoding="utf-8"),
        (ROOT / "docs" / "clinical_freeze_dossier.md").read_text(encoding="utf-8"),
    )
    assert audit.ready, audit.issues
