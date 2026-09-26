from pathlib import Path

import pandas as pd
import pytest

from mimic_sepsis.antimicrobials import (
    audit_antimicrobial_rules, classify_prescriptions, confirm_administrations,
    load_antimicrobial_rules, select_antimicrobial_starts,
)


RULES = pd.DataFrame({"pattern": ["ceftriaxone", "vancomycin"], "group": ["cephalosporin", "glycopeptide"]})


def prescriptions():
    return pd.DataFrame({
        "subject_id": [1, 1, 1], "hadm_id": [10, 10, 10], "pharmacy_id": [1, 2, 3],
        "drug": ["CefTRIAXone", "Vancomycin Ophth Oint", "Fentanyl"],
        "route": ["IV", "OD", "IV"], "drug_type": ["MAIN"] * 3,
        "starttime": ["2100-01-01"] * 3,
    })


def test_classification_includes_systemic_and_audits_exclusions():
    result = classify_prescriptions(prescriptions(), RULES)
    assert result.is_antimicrobial.tolist() == [True, False, False]
    assert result.classification_reason.tolist() == ["included", "excluded_form", "no_rule_match"]


def test_confirmation_uses_earliest_exact_administered_event_not_negation():
    classified = classify_prescriptions(prescriptions(), RULES)
    emar = pd.DataFrame({
        "subject_id": [1, 1, 1], "hadm_id": [10, 10, 10], "pharmacy_id": [1, 1, 1],
        "charttime": ["2100-01-01 01:00", "2100-01-01 02:00", "2100-01-01 03:00"],
        "event_txt": ["Not Administered", "Administered", "Administered"],
    })
    result = confirm_administrations(classified, emar)
    assert result.loc[0, "administration_time"] == pd.Timestamp("2100-01-01 02:00")


def test_start_selection_keeps_prescription_and_emar_evidence_distinct():
    classified = classify_prescriptions(prescriptions(), RULES)
    confirmed = classified.loc[classified["is_antimicrobial"]].assign(
        administration_time=pd.Timestamp("2100-01-01 02:00")
    )
    prescribed = select_antimicrobial_starts(
        classified, confirmed, evidence="qualifying_prescription_start"
    )
    administered = select_antimicrobial_starts(
        classified, confirmed,
        evidence="first_qualifying_emar_administration",
    )
    assert prescribed.loc[0, "antibiotic_time"] == pd.Timestamp("2100-01-01")
    assert administered.loc[0, "antibiotic_time"] == pd.Timestamp(
        "2100-01-01 02:00"
    )


def test_repository_rules_load():
    path = Path(__file__).parents[1] / "config" / "antimicrobial_rules.csv"
    rules = load_antimicrobial_rules(path)
    assert "vancomycin" in rules.pattern.tolist()


def test_rules_normalize_before_duplicate_validation(tmp_path):
    path = tmp_path / "rules.csv"
    path.write_text("pattern,group\n Vancomycin ,A\nvancomycin,b\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate normalized"):
        load_antimicrobial_rules(path)


def test_rule_audit_is_complete_identifier_free_and_detects_order_overlap(tmp_path):
    path = tmp_path / "rules.csv"
    path.write_text(
        "pattern,group\namoxicillin,penicillin\namoxicillin-clavulanate,penicillin\n",
        encoding="utf-8",
    )
    report = audit_antimicrobial_rules(path)
    assert report["rule_count"] == 2
    assert report["group_rule_counts"] == {"penicillin": 2}
    assert report["ordered_substring_overlaps"] == [{
        "first_position": 1,
        "first_pattern": "amoxicillin",
        "second_position": 2,
        "second_pattern": "amoxicillin-clavulanate",
    }]
    assert report["clinical_review_required"] is True
    assert "subject_id" not in str(report)
