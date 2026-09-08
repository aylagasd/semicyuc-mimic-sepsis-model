import pandas as pd
import pytest

from mimic_sepsis.sofa_resp_renal import (
    add_contemporaneous_invasive_ventilation,
    normalize_fio2,
    pair_pao2_with_fio2,
    urine_output_at_landmarks,
)


@pytest.mark.parametrize("raw,expected", [(0.21, 0.21), (1, 1), (21, 0.21), (100, 1)])
def test_normalize_fio2_boundaries(raw, expected):
    assert normalize_fio2(raw) == expected


@pytest.mark.parametrize("raw", [0, 0.2, 1.01, 20, 101])
def test_rejects_invalid_fio2(raw):
    with pytest.raises(ValueError, match="FiO2"):
        normalize_fio2(raw)


def test_pao2_pairing_uses_latest_past_fio2_and_never_future():
    pao2 = pd.DataFrame(
        {"stay_id": [1, 1], "itemid": [50821, 50821],
         "charttime": ["2020-01-01 12:00", "2020-01-01 18:00"], "valuenum": [80, 90]}
    )
    fio2 = pd.DataFrame(
        {"stay_id": [1, 1, 1], "itemid": [223835] * 3,
         "charttime": ["2020-01-01 11:00", "2020-01-01 12:01", "2020-01-01 13:00"],
         "valuenum": [40, 100, 0.5]}
    )
    result = pair_pao2_with_fio2(pao2, fio2, max_lookback="4h")
    assert result.loc[0, "fio2"] == 0.4
    assert result.loc[0, "pao2_fio2"] == 200
    assert pd.isna(result.loc[1, "fio2"])


def test_pao2_pairing_separates_stays_and_deduplicates():
    pao2 = pd.DataFrame(
        {"stay_id": [1, 1], "itemid": [50821, 50821],
         "charttime": ["2020-01-01 12:00"] * 2, "valuenum": [80, 80]}
    )
    fio2 = pd.DataFrame(
        {"stay_id": [2], "itemid": [223835],
         "charttime": ["2020-01-01 11:00"], "valuenum": [40]}
    )
    result = pair_pao2_with_fio2(pao2, fio2)
    assert len(result) == 1
    assert pd.isna(result.loc[0, "fio2"])


def test_ventilation_is_contemporaneous_and_interval_end_is_exclusive():
    respiratory = pd.DataFrame(
        {"stay_id": [1, 1, 1], "pao2_time": [
            "2020-01-01 09:59", "2020-01-01 10:00", "2020-01-01 12:00"
        ]}
    )
    procedures = pd.DataFrame(
        {"stay_id": [1], "itemid": [225792],
         "starttime": ["2020-01-01 10:00"], "endtime": ["2020-01-01 12:00"]}
    )
    result = add_contemporaneous_invasive_ventilation(respiratory, procedures)
    assert result["invasive_ventilation"].tolist() == [False, True, False]


def test_urine_output_excludes_future_negative_nonurine_and_duplicates():
    events = pd.DataFrame(
        {"stay_id": [1] * 6, "itemid": [226559, 226559, 226560, 226627, 999, 226631],
         "charttime": [
             "2020-01-01 12:01", "2020-01-01 12:01", "2020-01-02 11:00",
             "2020-01-02 10:00", "2020-01-02 09:00", "2020-01-02 13:00"
         ], "value": [100, 100, 200, -50, 500, 1000]}
    )
    landmarks = pd.DataFrame({"stay_id": [1], "landmark_time": ["2020-01-02 12:00"]})
    result = urine_output_at_landmarks(events, landmarks)
    assert result.loc[0, "urine_output_ml"] == 300


def test_urine_window_has_explicit_boundary_and_no_cross_stay_leakage():
    events = pd.DataFrame(
        {"stay_id": [1, 1, 2], "itemid": [226559] * 3,
         "charttime": ["2020-01-01 12:00", "2020-01-01 12:01", "2020-01-02 11:00"],
         "value": [100, 200, 1000]}
    )
    landmarks = pd.DataFrame({"stay_id": [1], "landmark_time": ["2020-01-02 12:00"]})
    result = urine_output_at_landmarks(events, landmarks)
    assert result.loc[0, "urine_output_ml"] == 200
