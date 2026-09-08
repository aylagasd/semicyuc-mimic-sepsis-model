import pandas as pd
import pytest

from mimic_sepsis.sofa_labs import (
    link_labs_to_icu_stays,
    normalize_sofa_labs,
    worst_sofa_labs_in_windows,
)


def _labs(rows):
    return pd.DataFrame(
        rows,
        columns=[
            "subject_id",
            "hadm_id",
            "itemid",
            "charttime",
            "valuenum",
            "valueuom",
        ],
    )


def test_normalizes_selected_itemids_and_units():
    source = _labs(
        [
            (1, 10, 51265, "2020-01-01 01:00", 123, "K/uL"),
            (1, 10, 50885, "2020-01-01 02:00", 34.208, "umol/L"),
            (1, 10, 52546, "2020-01-01 03:00", 176.8, "µmol/L"),
            (1, 10, 99999, "2020-01-01 04:00", 9, "mg/dL"),
        ]
    )
    result = normalize_sofa_labs(source)

    assert result["component"].tolist() == [
        "platelets",
        "bilirubin",
        "creatinine",
    ]
    assert result["value"].tolist() == pytest.approx([123, 2, 2])
    assert result["unit"].tolist() == ["10^9/L", "mg/dL", "mg/dL"]


def test_normalization_drops_incomplete_and_negative_values():
    source = _labs(
        [
            (1, 10, 50912, "bad-time", 1, "mg/dL"),
            (1, 10, 50912, "2020-01-01", -1, "mg/dL"),
            (1, 10, 50912, "2020-01-01", None, "mg/dL"),
        ]
    )
    assert normalize_sofa_labs(source).empty


def test_normalization_rejects_unknown_units():
    source = _labs([(1, 10, 50912, "2020-01-01", 1, "mmol/L")])
    with pytest.raises(ValueError, match="Unsupported.*creatinine:mmol/l"):
        normalize_sofa_labs(source)


def test_link_uses_subject_admission_and_half_open_stay_interval():
    normalized = normalize_sofa_labs(
        _labs(
            [
                (1, 10, 50912, "2020-01-01 00:00", 1, "mg/dL"),
                (1, 10, 50912, "2020-01-02 00:00", 2, "mg/dL"),
                (1, 11, 50912, "2020-01-01 01:00", 3, "mg/dL"),
            ]
        )
    )
    stays = pd.DataFrame(
        {
            "subject_id": [1],
            "hadm_id": [10],
            "stay_id": [100],
            "intime": ["2020-01-01 00:00"],
            "outtime": ["2020-01-02 00:00"],
        }
    )
    linked = link_labs_to_icu_stays(normalized, stays)

    assert linked["value"].tolist() == [1]
    assert linked["stay_id"].tolist() == [100]


def test_link_rejects_overlapping_stays():
    normalized = normalize_sofa_labs(
        _labs([(1, 10, 50912, "2020-01-01 12:00", 1, "mg/dL")])
    )
    stays = pd.DataFrame(
        {
            "subject_id": [1, 1],
            "hadm_id": [10, 10],
            "stay_id": [100, 101],
            "intime": ["2020-01-01", "2020-01-01 06:00"],
            "outtime": ["2020-01-02", "2020-01-03"],
        }
    )
    with pytest.raises(ValueError, match="more than one"):
        link_labs_to_icu_stays(normalized, stays)


def test_reduction_selects_component_specific_worst_and_window_boundaries():
    normalized = normalize_sofa_labs(
        _labs(
            [
                (1, 10, 51265, "2020-01-01 00:00", 100, "K/uL"),
                (1, 10, 51265, "2020-01-01 02:00", 50, "K/uL"),
                (1, 10, 50885, "2020-01-01 01:00", 2, "mg/dL"),
                (1, 10, 50885, "2020-01-01 03:00", 8, "mg/dL"),
                (1, 10, 50912, "2020-01-02 00:00", 9, "mg/dL"),
            ]
        )
    )
    stays = pd.DataFrame(
        {
            "subject_id": [1],
            "hadm_id": [10],
            "stay_id": [100],
            "intime": ["2020-01-01"],
            "outtime": ["2020-01-03"],
        }
    )
    linked = link_labs_to_icu_stays(normalized, stays)
    windows = pd.DataFrame(
        {
            "window_id": ["w1"],
            "stay_id": [100],
            "window_start": ["2020-01-01"],
            "window_end": ["2020-01-02"],
        }
    )
    result = worst_sofa_labs_in_windows(linked, windows).set_index("component")

    assert result.loc["platelets", "worst_value"] == 50
    assert result.loc["bilirubin", "worst_value"] == 8
    assert result.loc["creatinine", "worst_value"] == 9


def test_reduction_validates_windows_and_preserves_missingness():
    linked = pd.DataFrame(
        columns=[
            "lab_event_id",
            "subject_id",
            "hadm_id",
            "charttime",
            "itemid",
            "component",
            "value",
            "unit",
            "stay_id",
        ]
    )
    duplicate = pd.DataFrame(
        {
            "window_id": ["x", "x"],
            "stay_id": [1, 1],
            "window_start": ["2020-01-01", "2020-01-02"],
            "window_end": ["2020-01-02", "2020-01-03"],
        }
    )
    with pytest.raises(ValueError, match="unique"):
        worst_sofa_labs_in_windows(linked, duplicate)

    valid = duplicate.iloc[:1]
    assert worst_sofa_labs_in_windows(linked, valid).empty
