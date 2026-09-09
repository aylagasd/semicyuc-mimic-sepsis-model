import pandas as pd
import pytest

from mimic_sepsis.landmarks import build_landmark_outcomes, build_multiple_horizons


BASE = pd.Timestamp("2100-01-01")


def stays(outtime=BASE + pd.Timedelta(hours=20)):
    return pd.DataFrame({
        "subject_id": [1], "hadm_id": [10], "stay_id": [100],
        "intime": [BASE], "outtime": [outtime],
    })


def events(time):
    return pd.DataFrame({"stay_id": [100], "t0": [time]})


def test_first_landmark_is_after_six_hours():
    result = build_landmark_outcomes(stays(), events(pd.NaT))
    assert result.iloc[0].landmark_time == BASE + pd.Timedelta(hours=6)
    assert result.iloc[0].landmark_hour == 6


def test_event_at_landmark_is_prevalent_and_landmark_is_excluded():
    result = build_landmark_outcomes(stays(), events(BASE + pd.Timedelta(hours=6)))
    assert result.empty


def test_event_at_horizon_end_is_positive():
    result = build_landmark_outcomes(stays(), events(BASE + pd.Timedelta(hours=12)))
    first = result.iloc[0]
    assert first.landmark_time == BASE + pd.Timedelta(hours=6)
    assert first.outcome == 1


def test_event_after_horizon_is_negative_when_followup_complete():
    result = build_landmark_outcomes(stays(), events(BASE + pd.Timedelta(hours=13)))
    assert result.iloc[0].outcome == 0


def test_short_followup_without_event_is_censored_not_control():
    result = build_landmark_outcomes(
        stays(BASE + pd.Timedelta(hours=9)), events(pd.NaT)
    )
    assert pd.isna(result.iloc[0].outcome)
    assert not result.iloc[0].horizon_observed


def test_event_before_early_discharge_remains_positive():
    result = build_landmark_outcomes(
        stays(BASE + pd.Timedelta(hours=9)), events(BASE + pd.Timedelta(hours=8))
    )
    assert result.iloc[0].outcome == 1
    assert result.iloc[0].horizon_observed


def test_no_landmarks_are_generated_at_or_after_event():
    onset = BASE + pd.Timedelta(hours=9)
    result = build_landmark_outcomes(stays(), events(onset))
    assert result["landmark_time"].max() < onset


def test_multiple_horizons_are_long_format_and_unique():
    result = build_multiple_horizons(stays(), events(pd.NaT), horizons_hours=(3, 6))
    assert set(result["horizon_hours"]) == {3, 6}
    assert not result.duplicated(["stay_id", "landmark_time", "horizon_hours"]).any()


def test_duplicate_outcome_per_stay_is_rejected():
    duplicated = pd.DataFrame({"stay_id": [100, 100], "t0": [BASE, BASE]})
    with pytest.raises(ValueError, match="unique"):
        build_landmark_outcomes(stays(), duplicated)
