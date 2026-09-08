import pandas as pd
import pytest

from mimic_sepsis.sofa_neuro_cardio import (
    normalize_gcs_events,
    normalize_map_events,
    normalize_vasoactive_intervals,
    reconstruct_gcs,
)


def _gcs(rows):
    return pd.DataFrame(
        rows, columns=["stay_id", "charttime", "itemid", "value", "valuenum"]
    )


def test_gcs_normalization_detects_explicit_intubation_and_categories():
    events = _gcs([
        [1, "2020-01-01 00:00", 220739, "4 Spontaneously", None],
        [1, "2020-01-01 00:00", 223900, "1.0 ET/Trach", None],
        [1, "2020-01-01 00:00", 223901, "6 Obeys Commands", None],
        [1, "2020-01-01 00:00", 220739, "invalid", 8],
    ])
    result = normalize_gcs_events(events)
    assert dict(zip(result["component"], result["component_value"])) == {
        "eye": 4, "verbal": 1, "motor": 6
    }
    assert result.loc[result["component"].eq("verbal"), "intubated"].item() is True


def test_gcs_reconstruction_requires_contemporaneous_complete_components():
    events = _gcs([
        [1, "2020-01-01 00:00", 220739, "4", 4],
        [1, "2020-01-01 00:20", 223900, "5", 5],
        [1, "2020-01-01 00:40", 223901, "6", 6],
        [2, "2020-01-01 00:00", 220739, "4", 4],
        [2, "2020-01-01 03:00", 223900, "5", 5],
        [2, "2020-01-01 03:00", 223901, "6", 6],
    ])
    result = reconstruct_gcs(events, contemporaneous_minutes=60)
    assert result[["stay_id", "gcs_total", "component_span_minutes"]].to_dict("records") == [
        {"stay_id": 1, "gcs_total": 15, "component_span_minutes": 40.0}
    ]


def test_gcs_intubated_is_explicit_not_imputed_to_normal():
    events = _gcs([
        [1, "2020-01-01", 220739, "3", 3],
        [1, "2020-01-01", 223900, "1.0 ET/Trach", 1],
        [1, "2020-01-01", 223901, "5", 5],
    ])
    result = reconstruct_gcs(events)
    assert result.loc[0, "gcs_total"] == 9
    assert result.loc[0, "verbal_intubated"]


def test_negative_gcs_tolerance_is_rejected():
    with pytest.raises(ValueError, match="non-negative"):
        reconstruct_gcs(_gcs([]), contemporaneous_minutes=-1)


def test_exact_time_fast_path_requires_all_components_same_time():
    events = _gcs([
        [1, "2020-01-01 00:00", 220739, "4", 4],
        [1, "2020-01-01 00:00", 223900, "5", 5],
        [1, "2020-01-01 00:00", 223901, "6", 6],
    ])
    result = reconstruct_gcs(events, contemporaneous_minutes=0)
    assert result.loc[0, "gcs_total"] == 15


def test_map_filters_wrong_item_invalid_time_and_implausible_values():
    events = pd.DataFrame({
        "stay_id": [1, 1, 1, 1],
        "charttime": ["2020-01-01", "bad", "2020-01-01", "2020-01-01"],
        "itemid": [220052, 220052, 220052, 999],
        "valuenum": [69, 70, 400, 50],
    })
    result = normalize_map_events(events)
    assert result["map_mmhg"].tolist() == [69]


def test_vasoactive_intervals_use_rate_not_amount_and_normalize_units():
    events = pd.DataFrame({
        "stay_id": [1, 1, 1, 1],
        "starttime": ["2020-01-01"] * 4,
        "endtime": ["2020-01-01 01:00", "2020-01-01 01:00",
                    "2020-01-01 01:00", "2020-01-01 01:00"],
        "itemid": [221906, 221289, 221662, 221653],
        "rate": [0.11, None, 5, 2],
        "rateuom": ["mcg/kg/min", "mcg/kg/min", "mg/hour", "µg/kg/min"],
        "amount": [999, 999, 999, 999],
    })
    result = normalize_vasoactive_intervals(events)
    assert result[["drug", "dose_mcg_kg_min"]].to_dict("records") == [
        {"drug": "dobutamine", "dose_mcg_kg_min": 2.0},
        {"drug": "norepinephrine", "dose_mcg_kg_min": 0.11},
    ]


def test_vasoactive_intervals_reject_zero_rate_and_invalid_interval():
    events = pd.DataFrame({
        "stay_id": [1, 1],
        "starttime": ["2020-01-01 02:00", "2020-01-01"],
        "endtime": ["2020-01-01 01:00", "2020-01-01 01:00"],
        "itemid": [221906, 221906],
        "rate": [1, 0],
        "rateuom": ["mcg/kg/min", "mcg/kg/min"],
    })
    assert normalize_vasoactive_intervals(events).empty


def test_required_columns_are_reported():
    with pytest.raises(ValueError, match="rateuom"):
        normalize_vasoactive_intervals(pd.DataFrame())
