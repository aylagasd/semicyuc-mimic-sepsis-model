import pandas as pd

from mimic_sepsis.phenotype_audit import coverage_summary, pair_multiplicity


def test_pair_multiplicity_uses_prespecified_bands():
    pairs = pd.DataFrame({
        "hadm_id": [1] + [2] * 3 + [3] * 7 + [4] * 10,
        "antibiotic_id": range(21), "culture_id": range(100, 121),
    })
    result = pair_multiplicity(pairs).set_index("pairs_per_admission")["admissions"]
    assert result.to_dict() == {"1": 1, "2–4": 1, "5–9": 1, "≥10": 1}


def test_coverage_categories_are_mutually_exclusive():
    episodes = pd.DataFrame({
        "acute_window_covered": [True, False, False, False],
        "exclusion_reason": [pd.NA, pd.NA, "no_acute_sofa_hours", "no_overlapping_icu_stay"],
    })
    result = coverage_summary(episodes)
    assert result["episodes"].sum() == 4
    assert result["episodes"].tolist() == [1, 1, 1, 1]
