from datetime import timedelta

import pandas as pd

from mimic_sepsis.sensitivity import (
    cohort_policy_summary,
    evaluate_horizon_lookback_grid,
    feature_columns_for_window,
    feature_coverage_grid,
)


def test_feature_column_window_mapping_is_exact():
    assert feature_columns_for_window(
        ["map_min_24h", "heart_rate_last_24h"], window=6
    ) == ["map_min_6h", "heart_rate_last_6h"]


def test_cohort_policy_summary_compares_all_requested_policies():
    patients = pd.DataFrame({
        "subject_id": [1], "anchor_age": [50], "anchor_year": [2100]
    })
    admissions = pd.DataFrame({"subject_id": [1, 1], "hadm_id": [10, 11]})
    icustays = pd.DataFrame({
        "subject_id": [1, 1, 1], "hadm_id": [10, 10, 11],
        "stay_id": [100, 101, 102],
        "intime": [pd.Timestamp("2100-01-01") + timedelta(days=i) for i in range(3)],
        "outtime": [pd.Timestamp("2100-01-02") + timedelta(days=i) for i in range(3)],
    })
    result = cohort_policy_summary(patients, admissions, icustays)
    selected = dict(zip(result.policy, result.selected_icu_stays))
    assert selected == {"first_per_admission": 2, "first_per_patient": 1, "all": 3}


def test_feature_coverage_uses_explicit_missing_indicators():
    features = pd.DataFrame({
        "heart_rate_missing_6h": [False, True],
        "heart_rate_missing_24h": [False, False],
    })
    result = feature_coverage_grid(
        features, variables=["heart_rate"], lookbacks_hours=[6, 24]
    )
    assert result.observed.tolist() == [1, 2]
    assert result.percent_observed.tolist() == [50, 100]


def test_horizon_grid_returns_development_and_validation_metrics():
    features = pd.DataFrame({
        "subject_id": range(20), "hadm_id": range(100, 120),
        "stay_id": range(200, 220),
        "landmark_time": [pd.Timestamp("2100-01-01 06:00")] * 20,
        "map_min_6h": [float(value) for value in range(20)],
    })
    landmarks = pd.concat([
        features[["subject_id", "hadm_id", "stay_id", "landmark_time"]].assign(
            horizon_hours=horizon, horizon_observed=True,
            outcome=[int(subject % 3 == 0) for subject in range(20)],
        )
        for horizon in (3, 6)
    ], ignore_index=True)
    result = evaluate_horizon_lookback_grid(
        landmarks, landmarks, features, features,
        primary_columns=["map_min_24h"], horizons_hours=[3, 6],
        lookbacks_hours=[6], folds=2, c=1.0, seed=7,
    )
    assert len(result) == 4
    assert set(result["sample"]) == {"development_oof", "validation"}
