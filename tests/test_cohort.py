import pandas as pd
import pytest

from mimic_sepsis.cohort import StayPolicy, build_adult_icu_cohort


def synthetic_tables():
    patients = pd.DataFrame(
        {"subject_id": [1, 2, 3], "anchor_age": [40, 17, 70], "anchor_year": [2100] * 3}
    )
    admissions = pd.DataFrame({"subject_id": [1, 1, 2, 3], "hadm_id": [10, 11, 20, 30]})
    icustays = pd.DataFrame(
        {
            "subject_id": [1, 1, 1, 2, 3, 3],
            "hadm_id": [10, 10, 11, 20, 30, 30],
            "stay_id": [101, 102, 103, 201, 301, 302],
            "intime": [
                "2100-01-01", "2100-01-03", "2101-01-01", "2100-01-01",
                "2100-01-01", "2100-01-04",
            ],
            "outtime": [
                "2100-01-02", "2100-01-04", "2101-01-02", "2100-01-02",
                "2099-12-31", None,
            ],
        }
    )
    return patients, admissions, icustays


def test_first_per_admission_selects_chronological_stay_and_recomputes_age():
    result = build_adult_icu_cohort(*synthetic_tables())
    assert result.cohort["stay_id"].tolist() == [101, 103]
    assert result.cohort["age_at_icu"].tolist() == [40, 41]
    assert result.flow["selected_admissions"] == 2


def test_all_policy_preserves_all_eligible_stays():
    result = build_adult_icu_cohort(*synthetic_tables(), stay_policy=StayPolicy.ALL)
    assert result.cohort["stay_id"].tolist() == [101, 102, 103]


def test_audit_retains_explicit_exclusion_reasons():
    result = build_adult_icu_cohort(*synthetic_tables())
    reasons = dict(zip(result.audit.stay_id, result.audit.exclusion_reason))
    assert reasons[201] == "younger_than_minimum_age"
    assert reasons[301] == "non_positive_duration"
    assert reasons[302] == "missing_timestamp"
    assert reasons[102] == "not_selected:first_per_admission"


def test_missing_required_column_fails_early():
    patients, admissions, icustays = synthetic_tables()
    with pytest.raises(ValueError, match="anchor_year"):
        build_adult_icu_cohort(patients.drop(columns="anchor_year"), admissions, icustays)
