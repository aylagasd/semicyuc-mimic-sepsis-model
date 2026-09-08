import pandas as pd
import pytest

from mimic_sepsis.sofa_hourly import build_icustay_hourly_grid, rolling_worst_score


def test_grid_matches_clock_hour_and_includes_pre_hours():
    stays = pd.DataFrame({"subject_id":[1], "hadm_id":[10], "stay_id":[100]})
    chart = pd.DataFrame({
        "stay_id":[100,100], "itemid":[220045,220045],
        "charttime":["2100-01-01 10:05", "2100-01-01 12:20"],
    })
    grid = build_icustay_hourly_grid(stays, chart, pre_hours=1)
    assert grid.hr.tolist() == [-1,0,1,2,3]
    assert grid.endtime.iloc[0] == pd.Timestamp("2100-01-01 10:00")


def test_grid_excludes_stay_without_heart_rate():
    stays = pd.DataFrame({"subject_id":[1], "hadm_id":[10], "stay_id":[100]})
    chart = pd.DataFrame({"stay_id":[100], "itemid":[999], "charttime":["2100-01-01"]})
    assert build_icustay_hourly_grid(stays, chart).empty


def test_rolling_window_is_left_open_right_closed_and_has_no_future_leakage():
    grid = pd.DataFrame({"stay_id":[1], "hr":[0], "endtime":["2100-01-02 00:00"]})
    events = pd.DataFrame({
        "stay_id":[1,1,1,1],
        "event_time":["2100-01-01 00:00", "2100-01-01 00:01", "2100-01-02 00:00", "2100-01-02 00:01"],
        "score":[4,1,3,4],
    })
    result = rolling_worst_score(grid, events)
    assert result.loc[0, "score_24h"] == 3


def test_invalid_window_is_rejected():
    with pytest.raises(ValueError, match="positive"):
        rolling_worst_score(
            pd.DataFrame(columns=["stay_id","hr","endtime"]),
            pd.DataFrame(columns=["stay_id","event_time","score"]),
            window_hours=0,
        )
