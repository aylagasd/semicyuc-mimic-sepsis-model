import pandas as pd

from mimic_sepsis.feature_sources import normalize_lab_feature_events, normalize_vital_events


def test_fahrenheit_is_converted_and_invalid_vitals_are_removed():
    events = pd.DataFrame({
        "stay_id": [1, 1, 1], "itemid": [223761, 220045, 220277],
        "charttime": ["2100-01-01"] * 3, "valuenum": [98.6, 80, 150],
    })
    result = normalize_vital_events(events)
    assert result["variable"].tolist() == ["heart_rate", "temperature"]
    assert result.loc[result["variable"].eq("temperature"), "value"].iloc[0] == 37


def test_lab_is_linked_by_specimen_but_available_at_storetime():
    labs = pd.DataFrame({
        "subject_id": [1], "hadm_id": [10], "itemid": [50813],
        "charttime": ["2100-01-01 05:00"],
        "storetime": ["2100-01-01 07:00"], "valuenum": [3.2],
    })
    stays = pd.DataFrame({
        "subject_id": [1], "hadm_id": [10], "stay_id": [100],
        "intime": ["2100-01-01"], "outtime": ["2100-01-02"],
    })
    result = normalize_lab_feature_events(labs, stays)
    assert result.iloc[0].event_time == pd.Timestamp("2100-01-01 07:00")
    assert result.iloc[0].specimen_time == pd.Timestamp("2100-01-01 05:00")


def test_lab_without_storetime_is_not_backdated_into_predictors():
    labs = pd.DataFrame({
        "subject_id": [1], "hadm_id": [10], "itemid": [50912],
        "charttime": ["2100-01-01 05:00"], "storetime": [None], "valuenum": [1.2],
    })
    stays = pd.DataFrame({
        "subject_id": [1], "hadm_id": [10], "stay_id": [100],
        "intime": ["2100-01-01"], "outtime": ["2100-01-02"],
    })
    assert normalize_lab_feature_events(labs, stays).empty
