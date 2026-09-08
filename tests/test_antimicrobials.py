from pathlib import Path

import pandas as pd

from mimic_sepsis.antimicrobials import (
    classify_prescriptions, confirm_administrations, load_antimicrobial_rules,
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


def test_confirmation_uses_earliest_administered_event_not_not_given():
    classified = classify_prescriptions(prescriptions(), RULES)
    emar = pd.DataFrame({
        "subject_id": [1, 1, 1], "hadm_id": [10, 10, 10], "pharmacy_id": [1, 1, 1],
        "charttime": ["2100-01-01 01:00", "2100-01-01 02:00", "2100-01-01 03:00"],
        "event_txt": ["Not Given", "Administered", "Administered"],
    })
    result = confirm_administrations(classified, emar)
    assert result.loc[0, "administration_time"] == pd.Timestamp("2100-01-01 02:00")


def test_repository_rules_load():
    path = Path(__file__).parents[1] / "config" / "antimicrobial_rules.csv"
    rules = load_antimicrobial_rules(path)
    assert "vancomycin" in rules.pattern.tolist()
