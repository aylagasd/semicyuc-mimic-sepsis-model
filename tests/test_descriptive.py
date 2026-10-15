import pandas as pd
import pytest

from mimic_sepsis.descriptive import (
    categorical_descriptive_summary, continuous_descriptive_summary,
    feature_quality_summary, feature_source_quality_summary,
    feature_value_summary, outcome_burden_summary,
    outcome_timing_summary, partition_standardized_differences,
    prepare_descriptive_cohort, sofa_completeness_summary,
)


SPLIT = {
    "group_key": "subject_id",
    "proportions": {"development": 0.7, "validation": 0.15, "test": 0.15},
    "seed": 42,
}


def _cohort(n=40):
    base = pd.Timestamp("2100-01-01")
    return pd.DataFrame({
        "subject_id": range(n), "hadm_id": range(100, 100 + n),
        "stay_id": range(1000, 1000 + n), "intime": [base] * n,
        "outtime": [base + pd.Timedelta("2 days")] * n,
        "age_at_icu": range(40, 40 + n),
        "admittime": [base - pd.Timedelta("1 day")] * n,
        "dischtime": [base + pd.Timedelta("4 days")] * n,
        "discharge_location": ["HOME"] * n,
        "hospital_expire_flag": [0] * (n - 10) + [1] * 10,
        "gender": ["F", "M"] * (n // 2), "race": ["A"] * n,
        "admission_type": ["URGENT"] * n,
        "admission_location": ["ED"] * n, "insurance": ["Other"] * n,
        "first_careunit": ["MICU"] * n, "cohort_included": [True] * n,
    })


def _labels():
    sepsis = pd.DataFrame({
        "subject_id": range(12), "stay_id": range(1000, 1012),
        "sepsis3": [True] * 12,
        "t0": [pd.Timestamp("2100-01-01 12:00")] * 12,
    })
    shock = pd.DataFrame({
        "subject_id": range(10), "stay_id": range(1000, 1010),
        "septic_shock": [True] * 10,
        "shock_t0": [pd.Timestamp("2100-01-01 18:00")] * 10,
    })
    return sepsis, shock


def test_prepared_cohort_excludes_test_and_attaches_nested_outcomes():
    sepsis, shock = _labels()
    result = prepare_descriptive_cohort(
        _cohort(), sepsis, shock, split_config=SPLIT
    )
    assert set(result["partition"]) == {"development", "validation"}
    assert "test" not in set(result["partition"])
    assert result.loc[result["septic_shock"], "sepsis3"].all()
    assert result["icu_los_days"].eq(2).all()


def test_prepared_cohort_rejects_shock_outside_sepsis():
    sepsis, shock = _labels()
    shock.loc[len(shock)] = [39, 1039, True, pd.Timestamp("2100-01-01 18:00")]
    with pytest.raises(ValueError, match="subset"):
        prepare_descriptive_cohort(_cohort(), sepsis, shock, split_config=SPLIT)


def test_clinical_summaries_are_aggregate_and_use_no_p_values():
    sepsis, shock = _labels()
    cohort = prepare_descriptive_cohort(_cohort(), sepsis, shock, split_config=SPLIT)
    burden = outcome_burden_summary(cohort, privacy_minimum_cell=2)
    continuous = continuous_descriptive_summary(cohort, privacy_minimum_cell=2)
    categorical = categorical_descriptive_summary(cohort, privacy_minimum_cell=2)
    smd = partition_standardized_differences(cohort, privacy_minimum_cell=2)
    assert set(burden["endpoint"]) == {
        "sepsis3", "septic_shock", "hospital_mortality",
    }
    assert set(continuous["variable"]) == {
        "age_at_icu", "icu_los_days", "hospital_los_days",
    }
    assert {"gender", "race"}.issubset(set(categorical["variable"]))
    assert "standardized_difference" in smd
    assert not any("p_value" in column for column in smd)


def test_categorical_summary_complementarily_suppresses_small_cell():
    cohort = pd.DataFrame({
        "partition": ["development"] * 12,
        "gender": ["F"] * 11 + ["M"],
    })
    result = categorical_descriptive_summary(
        cohort, columns=["gender"], privacy_minimum_cell=10
    )
    overall = result.loc[result["sample"].eq("overall")]
    assert overall["privacy_suppressed"].all()
    assert overall["n"].isna().all()
    assert overall["complementary_suppressed"].sum() == 1


def test_continuous_summary_suppresses_small_missingness_cell():
    cohort = pd.DataFrame({
        "partition": ["development"] * 12,
        "sepsis3": [False] * 12,
        "age_at_icu": list(range(11)) + [pd.NA],
    })
    result = continuous_descriptive_summary(
        cohort, columns=["age_at_icu"], privacy_minimum_cell=10
    )
    assert result["privacy_suppressed"].all()
    assert result["missing"].isna().all()


def _features(n=20):
    return pd.DataFrame({
        "subject_id": range(n), "stay_id": range(n),
        "heart_rate_count_6h": [2] * n,
        "heart_rate_missing_6h": [False] * n,
        "heart_rate_count_12h": [3] * n,
        "heart_rate_missing_12h": [False] * n,
        "heart_rate_count_24h": [4] * n,
        "heart_rate_missing_24h": [False] * n,
        "heart_rate_last_24h": range(70, 70 + n),
    })


def test_feature_quality_and_value_summaries_are_partitioned():
    features = {"development": _features(), "validation": _features()}
    quality = feature_quality_summary(features, ["heart_rate"])
    values = feature_value_summary(features, ["heart_rate"])
    assert len(quality) == 6
    assert quality["percent_observed"].eq(100).all()
    assert len(values) == 2
    assert values["n"].eq(20).all()


def test_source_quality_audits_bounds_chronology_and_icu_linkage():
    chart = pd.DataFrame({
        "stay_id": [1, 1], "itemid": [220045, 220045],
        "charttime": ["2100-01-01 01:00", "2100-01-01 02:00"],
        "valuenum": [80, 999],
    })
    labs = pd.DataFrame({
        "subject_id": [1, 1], "hadm_id": [10, 10],
        "itemid": [50912, 50912],
        "charttime": ["2100-01-01 03:00", "2100-01-01 05:00"],
        "storetime": ["2100-01-01 04:00", "2100-01-01 04:00"],
        "valuenum": [1.2, 1.3],
    })
    cohort = pd.DataFrame({
        "subject_id": [1], "hadm_id": [10], "stay_id": [1],
        "intime": ["2100-01-01"], "outtime": ["2100-01-02"],
    })
    result = feature_source_quality_summary(
        chart, labs, cohort, privacy_minimum_cell=1
    ).set_index("variable")
    assert result.loc["heart_rate", "outside_bounds"] == 1
    assert result.loc["heart_rate", "accepted"] == 1
    assert result.loc["creatinine", "stored_before_specimen"] == 1
    assert result.loc["creatinine", "accepted"] == 1


def test_sofa_completeness_uses_only_permitted_cohort_rows():
    cohort = pd.DataFrame({
        "stay_id": [1, 2], "subject_id": [10, 20],
        "partition": ["development", "validation"],
    })
    sofa = pd.DataFrame({
        "stay_id": [1] * 10 + [2] * 10,
        "subject_id": [10] * 10 + [20] * 10,
        **{
            component: [0] * 20 for component in (
                "sofa_respiratory", "sofa_coagulation", "sofa_liver",
                "sofa_cardiovascular", "sofa_cns", "sofa_renal",
            )
        },
    })
    result = sofa_completeness_summary(sofa, cohort, privacy_minimum_cell=1)
    assert len(result) == 12
    assert result["percent_observed"].eq(100).all()


def test_timing_summary_suppresses_rare_demo_cells():
    sepsis, shock = _labels()
    cohort = prepare_descriptive_cohort(_cohort(), sepsis, shock, split_config=SPLIT)
    result = outcome_timing_summary(
        cohort, sepsis, shock, privacy_minimum_cell=100
    )
    assert result["privacy_suppressed"].all()
    assert result["n"].isna().all()
