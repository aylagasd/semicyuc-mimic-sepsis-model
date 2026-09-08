import pandas as pd
import pytest

from mimic_sepsis.infection import pair_antibiotics_and_cultures


def antibiotics(times):
    return pd.DataFrame({
        "subject_id": [1] * len(times), "hadm_id": [10] * len(times),
        "antibiotic_id": range(len(times)), "antibiotic_time": times,
    })


def cultures(times):
    return pd.DataFrame({
        "subject_id": [1] * len(times), "hadm_id": [10] * len(times),
        "culture_id": range(len(times)), "culture_time": times,
    })


def test_antibiotic_first_includes_24_hour_boundary():
    result = pair_antibiotics_and_cultures(
        antibiotics(["2100-01-01 00:00"]), cultures(["2100-01-02 00:00"])
    )
    assert result.loc[0, "pair_direction"] == "antibiotic_first"
    assert result.loc[0, "delta_hours"] == 24


def test_culture_first_includes_72_hour_boundary():
    result = pair_antibiotics_and_cultures(
        antibiotics(["2100-01-04 00:00"]), cultures(["2100-01-01 00:00"])
    )
    assert result.loc[0, "pair_direction"] == "culture_first"
    assert result.loc[0, "delta_hours"] == 72
    assert result.loc[0, "t_si"] == pd.Timestamp("2100-01-01")


def test_events_outside_windows_and_other_admissions_do_not_pair():
    abx = antibiotics(["2100-01-01"])
    culture = pd.concat([
        cultures(["2100-01-02 00:01"]),
        pd.DataFrame({"subject_id": [1], "hadm_id": [11], "culture_id": [9], "culture_time": ["2100-01-01"]}),
    ], ignore_index=True)
    assert pair_antibiotics_and_cultures(abx, culture).empty


def test_negative_window_is_rejected():
    with pytest.raises(ValueError, match="non-negative"):
        pair_antibiotics_and_cultures(antibiotics([]), cultures([]), antibiotic_first_hours=-1)
