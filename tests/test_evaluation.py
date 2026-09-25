import numpy as np
import pandas as pd
import pytest

from mimic_sepsis.evaluation import (
    calibration_metrics,
    decision_curve,
    operational_alert_metrics,
    patient_cluster_bootstrap_comparison,
    patient_cluster_bootstrap_estimates,
    percentile_intervals,
    threshold_metrics,
)
from mimic_sepsis.modeling import binary_metrics


def _table():
    return pd.DataFrame({
        "subject_id": np.repeat(np.arange(10), 2),
        "outcome": np.tile([0, 1], 10),
    })


def _legacy_bootstrap_estimates(table, probability, *, replicates, seed):
    """Reference implementation that physically duplicates sampled rows."""
    codes, subjects = pd.factorize(table["subject_id"], sort=False)
    positions = {
        code: np.flatnonzero(codes == code) for code in range(len(subjects))
    }
    rng = np.random.default_rng(seed)
    outcome = table["outcome"].to_numpy(int)
    rows = []
    for replicate in range(1, replicates + 1):
        sampled = rng.choice(len(subjects), size=len(subjects), replace=True)
        index = np.concatenate([positions[code] for code in sampled])
        rows.append({
            "replicate": replicate,
            **binary_metrics(outcome[index], probability[index]),
            **calibration_metrics(outcome[index], probability[index]),
        })
    return pd.DataFrame(rows)


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


def test_frequency_weighted_calibration_equals_physical_row_duplication():
    outcome = np.array([0, 1, 0, 1, 1, 0])
    probability = np.array([0.1, 0.8, 0.3, 0.7, 0.6, 0.2])
    frequency = np.array([0, 3, 2, 1, 4, 2])
    weighted = calibration_metrics(
        outcome, probability, sample_weight=frequency
    )
    repeated = calibration_metrics(
        np.repeat(outcome, frequency), np.repeat(probability, frequency)
    )
    for metric in weighted:
        assert weighted[metric] == pytest.approx(
            repeated[metric], rel=1e-10, abs=1e-10, nan_ok=True
        )


def test_vectorized_bootstrap_equals_physical_patient_resampling():
    table = pd.DataFrame({
        "subject_id": np.repeat([101, 202, 303, 404, 505, 606], [1, 2, 3, 1, 4, 2]),
        "outcome": [0, 0, 1, 0, 1, 1, 0, 1, 0, 1, 1, 0, 0],
    })
    probability = np.array([
        0.1, 0.2, 0.8, 0.3, 0.7, 0.7, 0.4,
        0.9, 0.2, 0.6, 0.8, 0.2, 0.1,
    ])
    expected = _legacy_bootstrap_estimates(
        table, probability, replicates=30, seed=17
    )
    actual = patient_cluster_bootstrap_estimates(
        table, probability, replicates=30, seed=17
    )
    pd.testing.assert_frame_equal(
        actual, expected[actual.columns], check_exact=False,
        rtol=1e-10, atol=1e-10,
    )


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


def test_operational_alert_metrics_count_episodes_and_warning_time():
    table = pd.DataFrame({
        "subject_id": [1, 1, 1, 2, 2],
        "stay_id": [10, 10, 10, 20, 20],
        "landmark_time": pd.to_datetime([
            "2100-01-01 06:00", "2100-01-01 07:00", "2100-01-01 09:00",
            "2100-01-02 06:00", "2100-01-02 07:00",
        ]),
        "event_time": pd.to_datetime([
            "2100-01-01 10:00", "2100-01-01 10:00", "2100-01-01 10:00",
            None, None,
        ]),
        "outcome": [1, 1, 1, 0, 0],
    })
    result = operational_alert_metrics(
        table, [0.6, 0.7, 0.8, 0.1, 0.6], threshold=0.5
    )
    assert result["alerts"] == 4
    assert result["alert_episodes"] == 3  # gap in stay 10 starts a new episode
    assert result["event_stays"] == 1
    assert result["event_stays_alerted"] == 1
    assert result["median_warning_hours"] == pytest.approx(4)
    assert result["alerts_per_100_patient_days"] == pytest.approx(1920)


def test_operational_metrics_do_not_invent_warning_for_missed_event():
    table = pd.DataFrame({
        "subject_id": [1], "stay_id": [10],
        "landmark_time": pd.to_datetime(["2100-01-01 06:00"]),
        "event_time": pd.to_datetime(["2100-01-01 07:00"]), "outcome": [1],
    })
    result = operational_alert_metrics(table, [0.1], threshold=0.5)
    assert result["event_stays_alerted"] == 0
    assert np.isnan(result["median_warning_hours"])


def test_alert_outside_prediction_horizon_is_not_credited_as_warning():
    table = pd.DataFrame({
        "subject_id": [1], "stay_id": [10],
        "landmark_time": pd.to_datetime(["2100-01-01 06:00"]),
        "event_time": pd.to_datetime(["2100-01-01 20:00"]), "outcome": [0],
    })
    result = operational_alert_metrics(table, [0.9], threshold=0.5)
    assert result["event_stays"] == 1
    assert result["event_stays_alerted"] == 0
    assert np.isnan(result["median_warning_hours"])


def test_false_alert_fraction_uses_alerts_as_denominator():
    table = pd.DataFrame({
        "subject_id": [1, 1, 2, 2], "stay_id": [10, 10, 20, 20],
        "landmark_time": pd.to_datetime([
            "2100-01-01 06:00", "2100-01-01 07:00",
            "2100-01-01 06:00", "2100-01-01 07:00",
        ]),
        "event_time": pd.to_datetime([
            "2100-01-01 08:00", "2100-01-01 08:00", None, None,
        ]),
        "outcome": [1, 1, 0, 0],
    })
    result = operational_alert_metrics(table, [0.8, 0.1, 0.9, 0.1], threshold=0.5)
    assert result["alerts"] == 2
    assert result["false_alert_fraction"] == pytest.approx(0.5)


def test_false_alert_fraction_is_undefined_without_alerts():
    table = pd.DataFrame({
        "subject_id": [1], "stay_id": [10],
        "landmark_time": pd.to_datetime(["2100-01-01 06:00"]),
        "event_time": pd.to_datetime([None]), "outcome": [0],
    })
    result = operational_alert_metrics(table, [0.1], threshold=0.5)
    assert np.isnan(result["false_alert_fraction"])


@pytest.mark.parametrize("threshold", [0, 1, -0.1, 1.1])
def test_invalid_operating_thresholds_fail(threshold):
    with pytest.raises(ValueError, match="threshold"):
        threshold_metrics([0, 1], [0.2, 0.8], threshold=threshold)
