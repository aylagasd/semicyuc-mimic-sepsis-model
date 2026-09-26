import pandas as pd
import pytest

from mimic_sepsis.infection import (
    pair_antibiotics_and_cultures, select_culture_collections,
    suspected_infection_parameters,
)


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
    assert str(result["antibiotic_time"].dtype) == "datetime64[ns]"


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


def test_versioned_infection_parameters_separate_primary_and_sensitivity():
    config = {
        "schema_version": 1,
        "phenotype": "suspected_infection_primary",
        "primary": {
            "antibiotic_evidence": "first_qualifying_emar_administration",
            "culture_scope": "blood_only",
            "antibiotic_first_hours": 24,
            "culture_first_hours": 72,
        },
        "sensitivities": {
            "prescription_start": {
                "antibiotic_evidence": "qualifying_prescription_start",
                "culture_scope": "blood_only",
                "antibiotic_first_hours": 24,
                "culture_first_hours": 72,
            }
        },
    }
    assert suspected_infection_parameters(config)["antibiotic_evidence"].startswith(
        "first_qualifying_emar"
    )
    assert suspected_infection_parameters(
        config, sensitivity="prescription_start"
    )["antibiotic_evidence"] == "qualifying_prescription_start"
    with pytest.raises(ValueError, match="Unknown suspected-infection sensitivity"):
        suspected_infection_parameters(config, sensitivity="unplanned")


def test_culture_scope_expands_specimens_and_deduplicates_collection():
    microbiology = pd.DataFrame({
        "subject_id": [1, 1, 1],
        "hadm_id": [10, 10, 10],
        "micro_specimen_id": [100, 100, 200],
        "charttime": ["2100-01-01 01:00", "2100-01-01 01:00", None],
        "chartdate": ["2100-01-01", "2100-01-01", "2100-01-02"],
        "spec_type_desc": ["BLOOD CULTURE", "BLOOD CULTURE", "URINE"],
    })

    blood = select_culture_collections(
        microbiology, culture_scope="blood_only"
    )
    expanded = select_culture_collections(
        microbiology, culture_scope="all_specimens"
    )

    assert blood["culture_id"].tolist() == [100]
    assert expanded["culture_id"].tolist() == [100, 200]
    assert expanded.loc[1, "culture_time"] == pd.Timestamp("2100-01-02")


def test_culture_selection_rejects_unknown_scope_and_incomplete_schema():
    with pytest.raises(ValueError, match="missing columns"):
        select_culture_collections(pd.DataFrame(), culture_scope="blood_only")
    incomplete = pd.DataFrame(columns=[
        "subject_id", "hadm_id", "micro_specimen_id", "charttime",
        "chartdate", "spec_type_desc",
    ])
    with pytest.raises(ValueError, match="Unsupported culture scope"):
        select_culture_collections(incomplete, culture_scope="respiratory_only")
