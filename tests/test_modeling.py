from datetime import timedelta

import numpy as np
import pandas as pd
import pytest

from mimic_sepsis.modeling import (
    assemble_modeling_table,
    binary_metrics,
    equal_patient_weights,
    grouped_cross_validation,
    grouped_prevalence_cross_validation,
    make_logistic_pipeline,
    patient_weighted_event_rate,
)


def _tables():
    landmarks = pd.DataFrame({
        "subject_id": [1, 1, 1], "hadm_id": [10] * 3, "stay_id": [100] * 3,
        "landmark_time": pd.to_datetime(["2100-01-01 06:00", "2100-01-01 06:00", "2100-01-01 07:00"]),
        "horizon_hours": [3, 6, 6], "horizon_observed": [True, True, False],
        "outcome": pd.array([0, 1, pd.NA], dtype="Int8"),
    })
    features = pd.DataFrame({
        "subject_id": [1, 1], "hadm_id": [10, 10], "stay_id": [100, 100],
        "landmark_time": pd.to_datetime(["2100-01-01 06:00", "2100-01-01 07:00"]),
        "heart_rate_last_24h": [80.0, 90.0],
    })
    return landmarks, features


def test_assembly_keeps_only_observed_primary_horizon():
    result = assemble_modeling_table(*_tables(), horizon_hours=6)
    assert len(result) == 1
    assert result.loc[0, "outcome"] == 1
    assert result.loc[0, "heart_rate_last_24h"] == 80


def test_equal_patient_weights_equalize_total_influence():
    table = pd.DataFrame({"subject_id": [1, 1, 1, 2]})
    weights = equal_patient_weights(table)
    totals = pd.Series(weights).groupby(table["subject_id"]).sum()
    assert totals.loc[1] == pytest.approx(totals.loc[2])
    assert weights.mean() == pytest.approx(1)


def test_patient_weighted_rate_is_mean_of_patient_rates():
    table = pd.DataFrame({"subject_id": [1, 1, 1, 2], "outcome": [1, 1, 1, 0]})
    assert patient_weighted_event_rate(table) == pytest.approx(0.5)


def test_binary_metrics_reject_invalid_probabilities_and_handles_one_class():
    metrics = binary_metrics([0, 0], [0.1, 0.2])
    assert np.isnan(metrics["auroc"])
    with pytest.raises(ValueError, match="probabilities"):
        binary_metrics([0], [1.1])


def test_grouped_cv_predicts_each_row_without_patient_overlap():
    rows = []
    for subject in range(20):
        for hour in range(2):
            rows.append({
                "subject_id": subject, "hadm_id": subject + 100,
                "stay_id": subject + 200,
                "landmark_time": pd.Timestamp("2100-01-01") + timedelta(hours=hour),
                "outcome": int(subject % 3 == 0 and hour == 1),
                "x": float(subject + hour),
            })
    table = pd.DataFrame(rows)
    pipeline = make_logistic_pipeline(["x"])
    predictions, metrics = grouped_cross_validation(
        table, pipeline, ["x"], folds=4, seed=7
    )
    assert len(predictions) == len(table)
    assert predictions.groupby("subject_id")["fold"].nunique().max() == 1
    assert len(metrics) == 4
    baseline, baseline_metrics = grouped_prevalence_cross_validation(
        table, folds=4, seed=7
    )
    assert len(baseline) == len(table)
    assert baseline.groupby("subject_id")["fold"].nunique().max() == 1
    assert len(baseline_metrics) == 4
