"""Reproducible construction of the adult ICU study base population."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import pandas as pd


class StayPolicy(StrEnum):
    """Policy for repeated eligible ICU stays."""

    ALL = "all"
    FIRST_PER_ADMISSION = "first_per_admission"
    FIRST_PER_PATIENT = "first_per_patient"


@dataclass(frozen=True)
class CohortResult:
    """Selected cohort, row-level audit table and aggregate flow counts."""

    cohort: pd.DataFrame
    audit: pd.DataFrame
    flow: dict[str, int]


def _require_columns(frame: pd.DataFrame, name: str, columns: set[str]) -> None:
    missing = sorted(columns - set(frame.columns))
    if missing:
        raise ValueError(f"{name} is missing columns: {', '.join(missing)}")


def build_adult_icu_cohort(
    patients: pd.DataFrame,
    admissions: pd.DataFrame,
    icustays: pd.DataFrame,
    *,
    minimum_age: int = 18,
    stay_policy: StayPolicy = StayPolicy.FIRST_PER_ADMISSION,
) -> CohortResult:
    """Build an adult ICU cohort and preserve explicit exclusion reasons.

    Age follows the MIMIC-IV anchor convention. Eligibility requires complete
    linkage, age at least ``minimum_age``, valid timestamps and positive ICU
    duration. Selection is chronological and deterministic using ``stay_id`` as
    a final tie-breaker.
    """
    _require_columns(
        patients,
        "patients",
        {"subject_id", "anchor_age", "anchor_year"},
    )
    _require_columns(admissions, "admissions", {"subject_id", "hadm_id"})
    _require_columns(
        icustays,
        "icustays",
        {"subject_id", "hadm_id", "stay_id", "intime", "outtime"},
    )
    if minimum_age < 0:
        raise ValueError("minimum_age must be non-negative")
    try:
        policy = StayPolicy(stay_policy)
    except ValueError as exc:
        raise ValueError(f"Unsupported stay policy: {stay_policy}") from exc

    stays = icustays.copy()
    stays["intime"] = pd.to_datetime(stays["intime"], errors="coerce")
    stays["outtime"] = pd.to_datetime(stays["outtime"], errors="coerce")
    stays = stays.merge(
        patients[["subject_id", "anchor_age", "anchor_year"]],
        on="subject_id",
        how="left",
        validate="many_to_one",
        indicator="patient_link",
    )
    stays = stays.merge(
        admissions[["subject_id", "hadm_id"]].drop_duplicates(),
        on=["subject_id", "hadm_id"],
        how="left",
        validate="many_to_one",
        indicator="admission_link",
    )
    stays["age_at_icu"] = (
        stays["anchor_age"] + stays["intime"].dt.year - stays["anchor_year"]
    )
    stays["exclusion_reason"] = pd.Series(pd.NA, index=stays.index, dtype="string")

    rules = [
        (stays["patient_link"] != "both", "missing_patient_link"),
        (stays["admission_link"] != "both", "missing_admission_link"),
        (stays["intime"].isna() | stays["outtime"].isna(), "missing_timestamp"),
        (stays["outtime"] <= stays["intime"], "non_positive_duration"),
        (stays["age_at_icu"].isna(), "missing_age"),
        (stays["age_at_icu"] < minimum_age, "younger_than_minimum_age"),
    ]
    for condition, reason in rules:
        unresolved = stays["exclusion_reason"].isna()
        stays.loc[unresolved & condition, "exclusion_reason"] = reason

    eligible = stays[stays["exclusion_reason"].isna()].copy()
    eligible = eligible.sort_values(["subject_id", "intime", "stay_id"])
    if policy == StayPolicy.FIRST_PER_ADMISSION:
        selected_index = eligible.drop_duplicates(
            ["subject_id", "hadm_id"], keep="first"
        ).index
    elif policy == StayPolicy.FIRST_PER_PATIENT:
        selected_index = eligible.drop_duplicates("subject_id", keep="first").index
    else:
        selected_index = eligible.index

    not_selected = eligible.index.difference(selected_index)
    stays.loc[not_selected, "exclusion_reason"] = f"not_selected:{policy.value}"
    stays["selected"] = stays.index.isin(selected_index)
    cohort = stays.loc[stays["selected"]].sort_values(
        ["subject_id", "intime", "stay_id"]
    )
    flow = {
        "source_icu_stays": int(len(stays)),
        "linked_icu_stays": int(
            ((stays["patient_link"] == "both") & (stays["admission_link"] == "both")).sum()
        ),
        "eligible_adult_icu_stays": int(len(eligible)),
        "selected_icu_stays": int(len(cohort)),
        "selected_patients": int(cohort["subject_id"].nunique()),
        "selected_admissions": int(cohort["hadm_id"].nunique()),
    }
    return CohortResult(
        cohort=cohort.reset_index(drop=True),
        audit=stays.reset_index(drop=True),
        flow=flow,
    )
