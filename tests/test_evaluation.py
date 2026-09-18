import numpy as np
import pandas as pd
import pytest

from mimic_sepsis.evaluation import (
    calibration_metrics,
    decision_curve,
    patient_cluster_bootstrap_comparison,
    patient_cluster_bootstrap_estimates,
    percentile_intervals,
    threshold_metrics,
)


def _table():
    return pd.DataFrame({
        "subject_id": np.repeat(np.arange(10), 2),
        "outcome": np.tile([0, 1], 10),
    })


def test_identical_models_have_zero_paired_differences():
    table = _table()
    probability = np.tile([0.2, 0.8], 10)
    result = patient_cluster_bootstrap_comparison(
        table, probability, probability, replicates=25, seed=3
    )
    assert (result.filter(like="delta_") == 0).all(axis=None)


def test_bootstrap_is_reproducible_and_retains_requested_replicates():
    table = _table()
    reference = np.repeat(0.5, len(table))
    candidate = np.tile([0.1, 0.9], 10)
    first = patient_cluster_bootstrap_comparison(
        table, reference, candidate, replicates=20, seed=7
    )
    second = patient_cluster_bootstrap_comparison(
        table, reference, candidate, replicates=20, seed=7
    )
    pd.testing.assert_frame_equal(first, second)
    assert len(first) == 20


def test_absolute_bootstrap_contains_calibration_and_is_reproducible():
    table = _table()
    probability = np.tile([0.2, 0.8], 10)
    first = patient_cluster_bootstrap_estimates(
        table, probability, replicates=8, seed=11
    )
    second = patient_cluster_bootstrap_estimates(
        table, probability, replicates=8, seed=11
    )
    pd.testing.assert_frame_equal(first, second)
    assert {"calibration_intercept", "calibration_slope", "auroc"} <= set(first)


def test_percentile_intervals_count_only_finite_estimates():
    bootstrap = pd.DataFrame({"replicate": [1, 2, 3], "delta_auroc": [0.1, np.nan, 0.3]})
    result = percentile_intervals(bootstrap, confidence_level=0.8).iloc[0]
    assert result.successful_replicates == 2
    assert result.lower == pytest.approx(0.12)
    assert result.upper == pytest.approx(0.28)


def test_invalid_probability_alignment_fails():
    with pytest.raises(ValueError, match="align"):
        patient_cluster_bootstrap_comparison(_table(), [0.5], [0.5], replicates=2)


def test_calibration_is_near_ideal_for_well_calibrated_grouped_risks():
    outcome = np.tile([0, 0, 0, 1, 0, 1, 1, 1], 50)
    probability = np.tile([0.25] * 4 + [0.75] * 4, 50)
    result = calibration_metrics(outcome, probability)
    assert result["calibration_intercept"] == pytest.approx(0, abs=1e-8)
    assert result["calibration_model_intercept"] == pytest.approx(0, abs=1e-8)
    assert result["calibration_slope"] == pytest.approx(1, abs=1e-8)


def test_calibration_is_undefined_with_one_class_or_constant_predictions():
    one_class = calibration_metrics([0, 0], [0.2, 0.3])
    assert all(np.isnan(value) for value in one_class.values())
    constant = calibration_metrics([0, 1], [0.5, 0.5])
    assert np.isnan(constant["calibration_slope"])
    assert constant["calibration_intercept"] == pytest.approx(0)


def test_threshold_metrics_use_greater_equal_boundary_and_explicit_undefined():
    result = threshold_metrics([1, 0, 1, 0], [0.5, 0.5, 0.49, 0.1], threshold=0.5)
    assert (result["tp"], result["fp"], result["tn"], result["fn"]) == (1, 1, 1, 1)
    assert result["sensitivity"] == pytest.approx(0.5)
    assert result["specificity"] == pytest.approx(0.5)
    no_alerts = threshold_metrics([0, 1], [0.1, 0.1], threshold=0.5)
    assert np.isnan(no_alerts["ppv"])


def test_decision_curve_matches_manual_net_benefit_and_includes_references():
    result = decision_curve([1, 0, 1, 0], [0.9, 0.8, 0.2, 0.1], thresholds=[0.5])
    assert set(result["strategy"]) == {"model", "treat_all", "treat_none"}
    model = result.loc[result["strategy"].eq("model"), "net_benefit"].item()
    assert model == pytest.approx(0.0)  # TP/n=.25, FP/n=.25, odds=.5/.5


@pytest.mark.parametrize("threshold", [0, 1, -0.1, 1.1])
def test_invalid_operating_thresholds_fail(threshold):
    with pytest.raises(ValueError, match="threshold"):
        threshold_metrics([0, 1], [0.2, 0.8], threshold=threshold)
