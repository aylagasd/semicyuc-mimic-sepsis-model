import pandas as pd

from mimic_sepsis.septic_shock import (
    build_septic_shock_labels, normalize_lactate, normalize_vasopressor_intervals,
)


def test_lactate_units_and_availability_are_normalized():
    events = pd.DataFrame({
        "subject_id": [1, 1], "hadm_id": [10, 10], "itemid": [50813, 50813],
        "charttime": ["2100-01-01", "2100-01-01 01:00"],
        "storetime": ["2100-01-01 00:30", "2100-01-01 01:30"],
        "valuenum": [3.0, 18.016], "valueuom": ["mmol/L", "mg/dL"],
    })
    result = normalize_lactate(events)
    assert result["lactate_mmol_l"].round(3).tolist() == [3.0, 2.0]
    assert result.loc[0, "lactate_available_at"] > result.loc[0, "lactate_time"]


def test_five_vasopressors_are_recognized_without_dobutamine():
    events = pd.DataFrame({
        "stay_id": [1] * 6, "itemid": [221906, 221289, 221662, 221749, 222315, 221653],
        "starttime": ["2100-01-01"] * 6, "endtime": ["2100-01-01 01:00"] * 6,
    })
    result = normalize_vasopressor_intervals(events)
    assert len(result) == 5
    assert "dobutamine" not in set(result["vasopressor"])


def test_shock_requires_strict_lactate_threshold_and_concurrency():
    t0 = pd.Timestamp("2100-01-02")
    sepsis = pd.DataFrame({"subject_id": [1], "hadm_id": [10], "stay_id": [100], "t0": [t0]})
    labs = pd.DataFrame({
        "subject_id": [1, 1], "hadm_id": [10, 10],
        "lactate_time": [t0, t0 + pd.Timedelta(hours=1)],
        "lactate_available_at": [t0, t0 + pd.Timedelta(hours=2)],
        "lactate_mmol_l": [2.0, 2.1],
    })
    vaso = pd.DataFrame({
        "stay_id": [100], "starttime": [t0 + pd.Timedelta(hours=3)],
        "endtime": [t0 + pd.Timedelta(hours=4)], "vasopressor": ["norepinephrine"],
    })
    result = build_septic_shock_labels(sepsis, labs, vaso).iloc[0]
    assert result.septic_shock
    assert result.lactate_mmol_l == 2.1
    assert result.shock_t0 == t0 + pd.Timedelta(hours=3)
    assert not result.adequate_fluids_verified


def test_nonconcurrent_criteria_do_not_label_shock():
    t0 = pd.Timestamp("2100-01-02")
    sepsis = pd.DataFrame({"subject_id": [1], "hadm_id": [10], "stay_id": [100], "t0": [t0]})
    labs = pd.DataFrame({
        "subject_id": [1], "hadm_id": [10], "lactate_time": [t0 - pd.Timedelta(hours=7)],
        "lactate_available_at": [t0 - pd.Timedelta(hours=7)], "lactate_mmol_l": [4.0],
    })
    vaso = pd.DataFrame({
        "stay_id": [100], "starttime": [t0], "endtime": [t0 + pd.Timedelta(hours=1)],
        "vasopressor": ["vasopressin"],
    })
    assert not build_septic_shock_labels(sepsis, labs, vaso).iloc[0].septic_shock
