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
