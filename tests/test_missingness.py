import numpy as np
import pandas as pd
import pytest

from mimic_sepsis.missingness import (
    attach_missingness_burden,
    feature_missingness_summary,
)


def test_missingness_summary_reports_safe_aggregate_counts():
    table = pd.DataFrame({
        "subject_id": np.repeat(range(10), 2),
        "stay_id": np.repeat(range(100, 110), 2),
        "x": [np.nan] * 10 + list(range(10)),
    })
    result = feature_missingness_summary(
        table, ("x",), privacy_minimum_cell=2
    ).iloc[0]
    assert not result.privacy_suppressed
    assert result.missing_landmarks == 10
    assert result.observed_landmarks == 10
    assert result.missing_fraction == pytest.approx(0.5)


def test_missingness_summary_suppresses_all_counts_for_small_patient_cell():
    table = pd.DataFrame({
        "subject_id": [1] * 10 + list(range(2, 12)),
        "stay_id": [101] * 10 + list(range(102, 112)),
        "x": [np.nan] * 10 + list(range(10)),
    })
    result = feature_missingness_summary(
        table, ("x",), privacy_minimum_cell=2
    ).iloc[0]
    assert result.privacy_suppressed
    assert pd.isna(result.landmarks)
    assert pd.isna(result.patients_with_missing)
    assert np.isnan(result.missing_fraction)


def test_zero_missingness_is_safe_to_report():
    table = pd.DataFrame({
        "subject_id": range(10), "stay_id": range(10, 20), "x": range(10),
    })
    result = feature_missingness_summary(
        table, ("x",), privacy_minimum_cell=10
    ).iloc[0]
    assert not result.privacy_suppressed
    assert result.missing_landmarks == 0


def test_attach_missingness_burden_uses_prespecified_groups():
    table = pd.DataFrame({
        "x": [1.0, np.nan, np.nan],
        "y": [2.0, 2.0, np.nan],
        "z": [3.0, 3.0, 3.0],
    })
    result = attach_missingness_burden(table, ("x", "y", "z"))
    assert result["missing_features"].tolist() == [0, 1, 2]
    assert result["missingness_group"].tolist() == [
        "0 missing", "1 missing", "2+ missing",
    ]


def test_missingness_rejects_duplicate_features_and_invalid_privacy_minimum():
    table = pd.DataFrame({"subject_id": [1], "stay_id": [2], "x": [1]})
    with pytest.raises(ValueError, match="unique"):
        feature_missingness_summary(table, ("x", "x"))
    with pytest.raises(ValueError, match="positive"):
        feature_missingness_summary(table, ("x",), privacy_minimum_cell=0)
