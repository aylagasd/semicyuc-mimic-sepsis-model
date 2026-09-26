import pandas as pd
import pytest

from mimic_sepsis.septic_shock import (
    SHOCK_COLUMNS, build_concurrency_sensitivity_labels,
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


def test_configured_lactate_itemids_reject_unknown_mappings():
    events = pd.DataFrame({
        "subject_id": [1], "hadm_id": [10], "itemid": [50813],
        "charttime": ["2100-01-01"], "valuenum": [3.0],
        "valueuom": ["mmol/L"],
    })
    assert len(normalize_lactate(events, [50813])) == 1
    with pytest.raises(ValueError, match="Unknown lactate itemids: 99999"):
        normalize_lactate(events, [99999])


def test_five_vasopressors_are_recognized_without_dobutamine():
    events = pd.DataFrame({
        "stay_id": [1] * 6, "itemid": [221906, 221289, 221662, 221749, 222315, 221653],
        "starttime": ["2100-01-01"] * 6, "endtime": ["2100-01-01 01:00"] * 6,
    })
    result = normalize_vasopressor_intervals(events)
    assert len(result) == 5
    assert "dobutamine" not in set(result["vasopressor"])


def test_configured_vasopressor_subset_is_effective_and_unknown_names_fail():
    events = pd.DataFrame({
        "stay_id": [1, 1], "itemid": [221906, 221749],
        "starttime": ["2100-01-01"] * 2,
        "endtime": ["2100-01-01 01:00"] * 2,
    })
    result = normalize_vasopressor_intervals(events, ["norepinephrine"])
    assert result["vasopressor"].tolist() == ["norepinephrine"]
    with pytest.raises(ValueError, match="Unknown vasopressors: dobutamine"):
        normalize_vasopressor_intervals(events, ["dobutamine"])


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


def test_asymmetric_sepsis_association_windows_are_honoured():
    t0 = pd.Timestamp("2100-01-02")
    sepsis = pd.DataFrame({"subject_id": [1], "hadm_id": [10], "stay_id": [100], "t0": [t0]})
    event_time = t0 - pd.Timedelta(hours=12)
    labs = pd.DataFrame({
        "subject_id": [1], "hadm_id": [10], "lactate_time": [event_time],
        "lactate_available_at": [event_time], "lactate_mmol_l": [4.0],
    })
    vaso = pd.DataFrame({
        "stay_id": [100], "starttime": [event_time],
        "endtime": [event_time + pd.Timedelta(hours=1)],
        "vasopressor": ["norepinephrine"],
    })
    excluded = build_septic_shock_labels(
        sepsis, labs, vaso,
        association_hours_before=6,
        association_hours_after=24,
    )
    included = build_septic_shock_labels(
        sepsis, labs, vaso,
        association_hours_before=24,
        association_hours_after=6,
    )
    assert not excluded.iloc[0].septic_shock
    assert included.iloc[0].septic_shock


def test_concurrency_sensitivities_are_recomputed_in_long_format():
    t0 = pd.Timestamp("2100-01-02")
    sepsis = pd.DataFrame({"subject_id": [1], "hadm_id": [10], "stay_id": [100], "t0": [t0]})
    labs = pd.DataFrame({
        "subject_id": [1], "hadm_id": [10], "lactate_time": [t0],
        "lactate_available_at": [t0], "lactate_mmol_l": [4.0],
    })
    vaso = pd.DataFrame({
        "stay_id": [100], "starttime": [t0 + pd.Timedelta(hours=10)],
        "endtime": [t0 + pd.Timedelta(hours=11)], "vasopressor": ["norepinephrine"],
    })
    result = build_concurrency_sensitivity_labels(
        sepsis, labs, vaso, concurrency_hours=[3, 12]
    )
    assert result["sensitivity"].tolist() == ["concurrency_3h", "concurrency_12h"]
    assert result["septic_shock"].tolist() == [False, True]
    assert result.groupby("stay_id").size().tolist() == [2]


def test_concurrency_sensitivity_windows_must_be_unique():
    empty = pd.DataFrame()
    with pytest.raises(ValueError, match="unique and non-negative"):
        build_concurrency_sensitivity_labels(
            empty, empty, empty, concurrency_hours=[3, 3]
        )


def test_empty_sepsis_preserves_shock_artifact_schema():
    sepsis = pd.DataFrame(columns=["subject_id", "hadm_id", "stay_id", "t0"])
    labs = pd.DataFrame(columns=[
        "subject_id", "hadm_id", "lactate_time", "lactate_available_at",
        "lactate_mmol_l",
    ])
    vaso = pd.DataFrame(columns=[
        "stay_id", "starttime", "endtime", "vasopressor",
    ])

    result = build_septic_shock_labels(sepsis, labs, vaso)

    assert result.empty
    assert result.columns.tolist() == SHOCK_COLUMNS
