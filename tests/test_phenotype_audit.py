import pandas as pd
import pytest

from mimic_sepsis.phenotype_audit import (
    complete_sofa_sensitivity_summary,
    coverage_sensitivity_summary,
    coverage_summary,
    decision_evidence_summary,
    infection_evidence_sensitivity_summary,
    infection_timing_summary,
    pair_multiplicity,
    shock_concurrency_sensitivity_summary,
    shock_proxy_summary,
    sofa_completeness_summary,
)


def test_pair_multiplicity_uses_prespecified_bands():
    pairs = pd.DataFrame({
        "hadm_id": [1] + [2] * 3 + [3] * 7 + [4] * 10,
        "antibiotic_id": range(21), "culture_id": range(100, 121),
    })
    result = pair_multiplicity(pairs).set_index("pairs_per_admission")["admissions"]
    assert result.to_dict() == {"1": 1, "2–4": 1, "5–9": 1, "≥10": 1}


def test_infection_evidence_sensitivity_reports_incremental_phenotypes():
    primary_pairs = pd.DataFrame({"hadm_id": [10, 20]})
    primary_stays = pd.DataFrame({"stay_id": [100]})
    sensitivity_pairs = pd.DataFrame({
        "sensitivity": ["prescription_start"] * 3,
        "hadm_id": [10, 20, 30],
    })
    sensitivity_stays = pd.DataFrame({
        "sensitivity": ["prescription_start", "prescription_start"],
        "stay_id": [100, 300],
    })
    result = infection_evidence_sensitivity_summary(
        primary_pairs, primary_stays, sensitivity_pairs, sensitivity_stays
    ).iloc[0]
    assert result.delta_pairs_vs_primary == 1
    assert result.delta_sepsis3_stays_vs_primary == 1
    assert result.primary_sepsis3_stays_retained == 1
    assert result.new_sepsis3_stays_vs_primary == 1


def test_infection_sensitivity_rejects_duplicate_stays():
    with pytest.raises(ValueError, match="duplicate stays"):
        infection_evidence_sensitivity_summary(
            pd.DataFrame({"hadm_id": [10]}),
            pd.DataFrame({"stay_id": [100]}),
            pd.DataFrame({
                "sensitivity": ["prescription_start"], "hadm_id": [10],
            }),
            pd.DataFrame({
                "sensitivity": ["prescription_start"] * 2,
                "stay_id": [100, 100],
            }),
        )


def test_coverage_categories_are_mutually_exclusive():
    episodes = pd.DataFrame({
        "acute_window_covered": [True, False, False, False],
        "exclusion_reason": [pd.NA, pd.NA, "no_acute_sofa_hours", "no_overlapping_icu_stay"],
    })
    result = coverage_summary(episodes)
    assert result["episodes"].sum() == 4
    assert result["episodes"].tolist() == [1, 1, 1, 1]


def test_coverage_rejects_unknown_exclusion_reason():
    with pytest.raises(ValueError, match="unexpected exclusion"):
        coverage_summary(pd.DataFrame({
            "acute_window_covered": [False],
            "exclusion_reason": ["new_unreviewed_reason"],
        }))


def test_coverage_sensitivities_preserve_predeclared_order_and_denominators():
    episodes = pd.DataFrame({
        "stay_id": [1, 1, 2, 3, pd.NA],
        "sepsis3": [True, True, True, False, False],
        "exclusion_reason": [pd.NA, pd.NA, pd.NA, pd.NA, "no_overlapping_icu_stay"],
        "baseline_assumed_zero": [False, False, True, False, False],
        "acute_window_covered": [False, True, True, True, False],
    })
    result = coverage_sensitivity_summary(episodes).set_index("sensitivity")
    assert result.index.tolist() == [
        "primary_no_coverage_exclusion",
        "baseline_observed",
        "full_acute_window",
        "baseline_observed_and_full_acute_window",
    ]
    assert result.loc["primary_no_coverage_exclusion"].to_dict() == {
        "eligible_pair_stay_rows": 4,
        "eligible_stays": 3,
        "positive_pair_stay_rows": 3,
        "sepsis3_stays": 2,
    }
    assert result.loc["baseline_observed_and_full_acute_window", "sepsis3_stays"] == 1


def test_complete_sofa_sensitivity_is_explicitly_named_and_available():
    episodes = pd.DataFrame({
        "stay_id": [1, 2],
        "sepsis3": [True, False],
        "exclusion_reason": [pd.NA, pd.NA],
        "baseline_assumed_zero": [False, False],
        "acute_window_covered": [True, True],
    })
    result = complete_sofa_sensitivity_summary(episodes)
    assert result["available"].all()
    assert result["sensitivity"].iloc[0] == "complete_sofa"
    assert result["sepsis3_stays"].iloc[0] == 1


def test_sofa_completeness_uses_one_primary_row_per_sepsis_stay():
    stays = pd.DataFrame({
        "stay_id": [1, 2, 3, 4, 5, 6],
        "sepsis3": [True, True, True, True, True, False],
        "missing_components_at_t0": [0, 1, 2, 4, pd.NA, 0],
    })
    result = sofa_completeness_summary(stays).set_index("component_missingness")
    assert result["sepsis3_stays"].to_dict() == {
        "0_complete": 1,
        "1_missing": 1,
        "2_to_3_missing": 1,
        "4_to_6_missing": 1,
        "unavailable": 1,
    }
    assert result["sepsis3_stays"].sum() == 5


def test_sofa_completeness_rejects_duplicate_primary_stays():
    with pytest.raises(ValueError, match="at most one row"):
        sofa_completeness_summary(pd.DataFrame({
            "stay_id": [1, 1],
            "sepsis3": [True, True],
            "missing_components_at_t0": [0, 1],
        }))


def test_infection_and_shock_summaries_are_aggregate_and_denominated():
    timing = infection_timing_summary(pd.DataFrame({
        "hadm_id": [1, 2, 3],
        "pair_direction": ["antibiotic_first", "culture_first", "unexpected"],
    }))
    assert timing["pairs"].sum() == 3
    assert timing.set_index("pair_direction").loc["unknown", "pairs"] == 1
    shock = shock_proxy_summary(pd.DataFrame({
        "septic_shock": [True, False, False],
        "adequate_fluids_verified": [False, False, False],
    })).set_index("metric")
    assert shock.loc["shock_proxy_positive", "count"] == 1
    assert shock.loc["adequate_fluids_not_verified", "count"] == 3


def test_shock_concurrency_sensitivities_compare_exact_stay_sets():
    primary = pd.DataFrame({
        "stay_id": [1, 2, 3], "septic_shock": [True, False, False],
    })
    sensitivities = pd.DataFrame({
        "sensitivity": ["concurrency_3h"] * 3 + ["concurrency_12h"] * 3,
        "concurrency_hours": [3] * 3 + [12] * 3,
        "stay_id": [1, 2, 3, 1, 2, 3],
        "septic_shock": [False, False, False, True, True, False],
    })
    result = shock_concurrency_sensitivity_summary(
        primary, sensitivities
    ).set_index("sensitivity")
    assert result.loc["concurrency_3h", "delta_positive_vs_primary"] == -1
    assert result.loc["concurrency_12h", "delta_positive_vs_primary"] == 1
    assert result.loc["concurrency_12h", "agreement_with_primary"] == 2


def test_shock_sensitivity_rejects_incomplete_stay_sets():
    primary = pd.DataFrame({"stay_id": [1, 2], "septic_shock": [False, False]})
    sensitivity = pd.DataFrame({
        "sensitivity": ["concurrency_3h"], "concurrency_hours": [3],
        "stay_id": [1], "septic_shock": [False],
    })
    with pytest.raises(ValueError, match="every primary stay once"):
        shock_concurrency_sensitivity_summary(primary, sensitivity)


def test_decision_evidence_never_claims_automatic_freeze():
    result = decision_evidence_summary().set_index("decision_id")
    assert set(result.index) == {"D002", "D004", "D010", "D011"}
    assert result.loc["D002", "evidence_in_report"] == "not_comparative"
    assert result.loc["D011", "evidence_in_report"] == "quantitative_coverage_sensitivities"
    assert result.loc["D010", "evidence_in_report"] == "descriptive_only"
    assert result.loc["D004", "evidence_in_report"] == "descriptive_only"
    with_sensitivity = decision_evidence_summary(
        shock_sensitivity_available=True
    ).set_index("decision_id")
    assert (
        with_sensitivity.loc["D010", "evidence_in_report"]
        == "quantitative_concurrency_sensitivities"
    )
    with_infection = decision_evidence_summary(
        infection_sensitivity_available=True
    ).set_index("decision_id")
    assert (
        with_infection.loc["D004", "evidence_in_report"]
        == "quantitative_prescription_start_sensitivity"
    )


def test_audit_rejects_missing_required_columns():
    with pytest.raises(ValueError, match="pair_direction"):
        infection_timing_summary(pd.DataFrame({"hadm_id": [1]}))
