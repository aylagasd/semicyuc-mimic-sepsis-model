import numpy as np
import pandas as pd
import pytest

from mimic_sepsis.recalibration import (
    calibration_readiness,
    fit_logistic_recalibrator,
)


def _table(patients=200):
    return pd.DataFrame({
        "subject_id": np.arange(patients),
        "outcome": np.tile([0, 1], patients // 2),
    })


def test_readiness_uses_patient_clusters_and_suppresses_small_counts():
    table = pd.DataFrame({
        "subject_id": [1, 1, 2, 2, 3, 3],
        "outcome": [0, 1, 0, 0, 0, 0],
    })
    result = calibration_readiness(
        table, minimum_event_patients=2, minimum_nonevent_patients=2,
        privacy_minimum_cell=2,
    )
    assert not result.ready
    assert result.event_patients is None
    assert result.nonevent_patients == 2
    assert result.reason_codes == ("insufficient_event_patients",)


def test_recalibrator_recovers_near_identity_for_calibrated_probabilities():
    table = _table()
    probability = np.tile([0.25] * 2 + [0.75] * 2, 50)
    table["outcome"] = np.tile([0, 1, 0, 1], 50)
    model = fit_logistic_recalibrator(
        table, probability,
        minimum_event_patients=50, minimum_nonevent_patients=50,
    )
    assert model.intercept == pytest.approx(0, abs=1e-6)
    assert model.slope == pytest.approx(0, abs=1e-6)
    # Both risk groups have 50% events, so recalibration becomes a constant 0.5.
    assert model.predict([0.25, 0.75]).tolist() == pytest.approx([0.5, 0.5])


def test_recalibrator_identity_when_grouped_risks_are_calibrated():
    table = pd.DataFrame({
        "subject_id": np.arange(400),
        "outcome": np.tile([0, 0, 0, 1, 0, 1, 1, 1], 50),
    })
    probability = np.tile([0.25] * 4 + [0.75] * 4, 50)
    model = fit_logistic_recalibrator(
        table, probability,
        minimum_event_patients=100, minimum_nonevent_patients=100,
    )
    assert model.intercept == pytest.approx(0, abs=1e-6)
    assert model.slope == pytest.approx(1, abs=1e-6)
    assert model.predict([0.25, 0.75]).tolist() == pytest.approx([0.25, 0.75])


def test_recalibrator_refuses_insufficient_patient_information():
    with pytest.raises(ValueError, match="prespecified patient information"):
        fit_logistic_recalibrator(
            _table(20), np.repeat(0.5, 20),
            minimum_event_patients=20, minimum_nonevent_patients=20,
        )


def test_recalibrator_rejects_invalid_probabilities():
    with pytest.raises(ValueError, match="probabilities"):
        fit_logistic_recalibrator(
            _table(), np.repeat(1.1, 200),
            minimum_event_patients=50, minimum_nonevent_patients=50,
        )
