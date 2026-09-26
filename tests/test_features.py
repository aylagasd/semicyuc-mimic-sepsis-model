import numpy as np
import pandas as pd
import pytest

from mimic_sepsis.features import (
    build_numeric_feature_matrix,
    multiwindow_numeric_features,
    numeric_window_features,
)


L = pd.Timestamp("2100-01-02")


def landmarks():
    return pd.DataFrame({
        "subject_id": [1], "hadm_id": [10], "stay_id": [100],
        "landmark_time": [L],
    })


def events(times, values):
    return pd.DataFrame({"stay_id": [100] * len(times), "event_time": times, "value": values})


def test_window_is_left_closed_and_right_open():
    result = numeric_window_features(
        landmarks(),
        events([L - pd.Timedelta(hours=24), L - pd.Timedelta(hours=1), L], [1, 2, 999]),
        variable="heart_rate", lookback_hours=24,
    ).iloc[0]
    assert result.heart_rate_count_24h == 2
    assert result.heart_rate_last_24h == 2


def test_post_landmark_event_cannot_change_features():
    before = events([L - pd.Timedelta(hours=1)], [80])
    after = pd.concat([before, events([L + pd.Timedelta(hours=1)], [999])], ignore_index=True)
    first = numeric_window_features(landmarks(), before, variable="heart_rate")
    second = numeric_window_features(landmarks(), after, variable="heart_rate")
    pd.testing.assert_frame_equal(first, second)


def test_slope_and_hours_since_last_have_clinical_units():
    result = numeric_window_features(
        landmarks(), events([L - pd.Timedelta(hours=3), L - pd.Timedelta(hours=1)], [10, 14]),
        variable="lactate",
    ).iloc[0]
    assert result.lactate_slope_24h == pytest.approx(2.0)
    assert result.lactate_hours_since_last_24h == 1.0


def test_missingness_is_explicit():
    result = numeric_window_features(landmarks(), events([], []), variable="map").iloc[0]
    assert result.map_count_24h == 0
    assert result.map_missing_24h
    assert pd.isna(result.map_last_24h)


def test_multiwindow_output_is_unique_and_named():
    result = multiwindow_numeric_features(
        landmarks(), events([L - pd.Timedelta(hours=8)], [7]), variable="creatinine"
    )
    assert result.creatinine_count_6h.iloc[0] == 0
    assert result.creatinine_count_12h.iloc[0] == 1
    assert result.creatinine_count_24h.iloc[0] == 1
    assert not result.duplicated(["stay_id", "landmark_time"]).any()


def test_matrix_deduplicates_horizons_and_never_copies_outcomes():
    points = pd.concat([landmarks(), landmarks().assign(horizon_hours=12)])
    source = events([L - pd.Timedelta(hours=1)], [80]).assign(variable="heart_rate")
    result = build_numeric_feature_matrix(
        points, source, variables=("heart_rate",), lookbacks_hours=(6,)
    )
    assert len(result) == 1
    assert result.loc[0, "heart_rate_last_6h"] == 80
    assert not any(column.startswith("outcome") for column in result)


def test_empty_landmark_matrix_keeps_a_stable_schema():
    empty = landmarks().iloc[0:0]
    result = build_numeric_feature_matrix(
        empty, events([], []).assign(variable=pd.Series(dtype="object")),
        variables=("map",), lookbacks_hours=(6,),
    )
    assert result.empty
    assert "map_missing_6h" in result


def test_vectorized_windows_match_direct_reference_across_stays():
    points = pd.DataFrame({
        "subject_id": [2, 1, 1, 3],
        "hadm_id": [20, 10, 10, 30],
        "stay_id": [200, 100, 100, 300],
        "landmark_time": pd.to_datetime([
            "2100-01-03 12:00", "2100-01-02 12:00",
            "2100-01-03 00:00", "2100-01-02 12:00",
        ]),
    })
    source = pd.DataFrame({
        "stay_id": [100, 100, 100, 100, 200, 200],
        "event_time": pd.to_datetime([
            "2100-01-01 12:00", "2100-01-02 11:00",
            "2100-01-02 11:00", "2100-01-03 00:00",
            "2100-01-03 06:00", "2100-01-03 11:00",
        ]),
        "value": [1.0, 2.0, 4.0, 8.0, 10.0, 20.0],
    })
    actual = numeric_window_features(
        points, source, variable="heart_rate", lookback_hours=24
    )

    expected_rows = []
    for point in points.itertuples(index=False):
        lower = point.landmark_time - pd.Timedelta(hours=24)
        window = source.loc[
            source["stay_id"].eq(point.stay_id)
            & source["event_time"].ge(lower)
            & source["event_time"].lt(point.landmark_time)
        ].sort_values("event_time")
        values = window["value"].to_numpy(dtype=float)
        times = window["event_time"].to_numpy(dtype="datetime64[ns]")
        count = len(window)
        slope = np.nan
        if count >= 2:
            x = (times - times[0]) / np.timedelta64(1, "h")
            if np.ptp(x) > 0:
                slope = np.polyfit(x, values, 1)[0]
        expected_rows.append({
            "subject_id": point.subject_id,
            "hadm_id": point.hadm_id,
            "stay_id": point.stay_id,
            "landmark_time": point.landmark_time,
            "heart_rate_count_24h": count,
            "heart_rate_missing_24h": count == 0,
            "heart_rate_last_24h": np.nan if not count else values[-1],
            "heart_rate_min_24h": np.nan if not count else values.min(),
            "heart_rate_max_24h": np.nan if not count else values.max(),
            "heart_rate_mean_24h": np.nan if not count else values.mean(),
            "heart_rate_std_24h": np.nan if count < 2 else values.std(ddof=1),
            "heart_rate_slope_24h": slope,
            "heart_rate_hours_since_last_24h": np.nan if not count else (
                np.datetime64(point.landmark_time, "ns") - times[-1]
            ) / np.timedelta64(1, "h"),
        })
    expected = pd.DataFrame(expected_rows)

    pd.testing.assert_frame_equal(actual, expected, check_exact=False, rtol=1e-12)
