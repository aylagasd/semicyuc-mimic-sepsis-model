import pytest

from mimic_sepsis.model_freeze import validate_model_freeze_document


def _valid():
    return {
        "schema_version": 1,
        "status": "frozen",
        "test_access": "locked_until_release",
        "frozen_at_utc": "2026-09-23T12:00:00Z",
        "data_version": "3.1",
        "source_run_id": "full-3.1-example",
        "code_commit": "abcdef1234567890",
        "primary_target": "sepsis3",
        "horizon_hours": 6,
        "feature_columns": ["heart_rate_last_24h", "map_min_24h"],
        "primary_model": "logistic",
        "model_parameters": {"C": 1.0},
        "calibration": {"method": "none", "intercept": None, "slope": None},
        "operating_thresholds": [0.05, 0.1],
        "decision_statuses": {
            key: "frozen" for key in (
                "D002", "D004", "D010", "D011", "D014", "D016", "D027", "D029",
                "D031",
            )
        },
        "validation_report_sha256": "a" * 64,
    }


def test_complete_model_freeze_is_valid():
    result = validate_model_freeze_document(_valid())
    assert result.primary_model == "logistic"
    assert result.operating_thresholds == (0.05, 0.1)


@pytest.mark.parametrize("field", ["operating_thresholds", "feature_columns"])
def test_model_freeze_rejects_empty_test_sensitive_choice(field):
    value = _valid()
    value[field] = []
    with pytest.raises(ValueError, match=field):
        validate_model_freeze_document(value)


def test_model_freeze_rejects_unfrozen_decision():
    value = _valid()
    value["decision_statuses"]["D029"] = "provisional"
    with pytest.raises(ValueError, match="D029"):
        validate_model_freeze_document(value)


def test_model_freeze_requires_finite_recalibration_coefficients():
    value = _valid()
    value["calibration"] = {
        "method": "logistic_intercept_and_slope", "intercept": 0.1, "slope": None,
    }
    with pytest.raises(ValueError, match="slope"):
        validate_model_freeze_document(value)
