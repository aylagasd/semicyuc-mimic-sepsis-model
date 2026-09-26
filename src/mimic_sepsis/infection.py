"""Temporal pairing primitives for the suspected-infection phenotype."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd


PAIR_COLUMNS = [
    "subject_id", "hadm_id", "antibiotic_id", "antibiotic_time",
    "culture_id", "culture_time", "pair_direction", "delta_hours", "t_si",
]

CULTURE_COLUMNS = ["subject_id", "hadm_id", "culture_id", "culture_time"]


def suspected_infection_parameters(
    config: Mapping[str, Any], *, sensitivity: str | None = None
) -> dict[str, Any]:
    """Validate the versioned infection definition and return its parameters."""
    if config.get("schema_version") != 1:
        raise ValueError("Unsupported suspected-infection configuration schema")
    if config.get("phenotype") != "suspected_infection_primary":
        raise ValueError("Unexpected suspected-infection phenotype identifier")
    if sensitivity is None:
        definition = config.get("primary")
    else:
        try:
            definition = config["sensitivities"][sensitivity]
        except (KeyError, TypeError) as error:
            raise ValueError(
                f"Unknown suspected-infection sensitivity: {sensitivity}"
            ) from error
    if not isinstance(definition, Mapping):
        raise ValueError("Malformed suspected-infection definition")
    allowed_evidence = {
        "first_qualifying_emar_administration",
        "qualifying_prescription_start",
    }
    evidence = definition.get("antibiotic_evidence")
    if evidence not in allowed_evidence:
        raise ValueError("Unsupported antimicrobial evidence")
    culture_scope = definition.get("culture_scope")
    if culture_scope not in {"blood_only", "all_specimens"}:
        raise ValueError("Unsupported culture scope")
    windows = {
        key: definition.get(key)
        for key in ("antibiotic_first_hours", "culture_first_hours")
    }
    if any(
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or value < 0
        for value in windows.values()
    ):
        raise ValueError("Infection pairing windows must be non-negative numbers")
    parameters = {
        "antibiotic_evidence": evidence,
        "culture_scope": culture_scope,
        **windows,
    }
    if sensitivity is not None:
        primary = suspected_infection_parameters(config)
        changed_axes = {
            "antibiotic_evidence": (
                parameters["antibiotic_evidence"]
                != primary["antibiotic_evidence"]
            ),
            "culture_scope": (
                parameters["culture_scope"] != primary["culture_scope"]
            ),
            "pairing_windows": (
                parameters["antibiotic_first_hours"],
                parameters["culture_first_hours"],
            ) != (
                primary["antibiotic_first_hours"],
                primary["culture_first_hours"],
            ),
        }
        changed = [name for name, differs in changed_axes.items() if differs]
        if len(changed) != 1:
            raise ValueError(
                "A suspected-infection sensitivity must change exactly one "
                "axis relative to primary"
            )
    return parameters


def select_culture_collections(
    microbiology: pd.DataFrame, *, culture_scope: str
) -> pd.DataFrame:
    """Return deduplicated specimen collections for an infection definition.

    ``blood_only`` matches specimen descriptions containing ``BLOOD``;
    ``all_specimens`` retains every timestamped microbiology specimen. A
    specimen represented by multiple organism rows remains one collection.
    """
    required = {
        "subject_id", "hadm_id", "micro_specimen_id", "charttime",
        "chartdate", "spec_type_desc",
    }
    missing = sorted(required - set(microbiology.columns))
    if missing:
        raise ValueError(
            "microbiology is missing columns: " + ", ".join(missing)
        )
    if culture_scope not in {"blood_only", "all_specimens"}:
        raise ValueError(f"Unsupported culture scope: {culture_scope}")

    selected = microbiology.copy()
    selected["culture_time"] = pd.to_datetime(
        selected["charttime"], errors="coerce"
    ).fillna(pd.to_datetime(selected["chartdate"], errors="coerce"))
    if culture_scope == "blood_only":
        selected = selected.loc[
            selected["spec_type_desc"].fillna("").str.contains(
                "BLOOD", case=False
            )
        ]
    return (
        selected.dropna(
            subset=["subject_id", "hadm_id", "micro_specimen_id", "culture_time"]
        )
        .sort_values("culture_time")
        .drop_duplicates(["subject_id", "hadm_id", "micro_specimen_id"])
        [["subject_id", "hadm_id", "micro_specimen_id", "culture_time"]]
        .rename(columns={"micro_specimen_id": "culture_id"})
        .loc[:, CULTURE_COLUMNS]
        .reset_index(drop=True)
    )


def pair_antibiotics_and_cultures(
    antibiotics: pd.DataFrame,
    cultures: pd.DataFrame,
    *,
    antibiotic_first_hours: float = 24,
    culture_first_hours: float = 72,
) -> pd.DataFrame:
    """Return qualifying antibiotic-culture pairs within each admission.

    Inputs must already represent clinically curated systemic antimicrobial
    starts and deduplicated culture collections. This function deliberately
    performs no drug/specimen classification. Boundaries are inclusive and
    ``t_si`` is the earlier event time.
    """
    required_antibiotic = {"subject_id", "hadm_id", "antibiotic_id", "antibiotic_time"}
    required_culture = {"subject_id", "hadm_id", "culture_id", "culture_time"}
    for frame, required, name in [
        (antibiotics, required_antibiotic, "antibiotics"),
        (cultures, required_culture, "cultures"),
    ]:
        missing = sorted(required - set(frame.columns))
        if missing:
            raise ValueError(f"{name} is missing columns: {', '.join(missing)}")
    if antibiotic_first_hours < 0 or culture_first_hours < 0:
        raise ValueError("Pairing windows must be non-negative")
    if antibiotics.empty or cultures.empty:
        return pd.DataFrame(columns=PAIR_COLUMNS)

    antibiotics = antibiotics[list(required_antibiotic)].copy()
    cultures = cultures[list(required_culture)].copy()
    antibiotics["antibiotic_time"] = pd.to_datetime(
        antibiotics["antibiotic_time"], errors="coerce"
    )
    cultures["culture_time"] = pd.to_datetime(cultures["culture_time"], errors="coerce")
    antibiotics = antibiotics.dropna(subset=["subject_id", "hadm_id", "antibiotic_time"])
    cultures = cultures.dropna(subset=["subject_id", "hadm_id", "culture_time"])

    pairs = antibiotics.merge(
        cultures, on=["subject_id", "hadm_id"], how="inner", validate="many_to_many"
    )
    delta_hours = (
        pairs["culture_time"] - pairs["antibiotic_time"]
    ).dt.total_seconds() / 3600
    antibiotic_first = delta_hours.between(0, antibiotic_first_hours, inclusive="both")
    culture_first = delta_hours.between(-culture_first_hours, 0, inclusive="both")
    pairs = pairs.loc[antibiotic_first | culture_first].copy()
    delta_hours = delta_hours.loc[pairs.index]
    pairs["pair_direction"] = "antibiotic_first"
    pairs.loc[delta_hours < 0, "pair_direction"] = "culture_first"
    pairs["delta_hours"] = delta_hours.abs()
    pairs["t_si"] = pairs[["antibiotic_time", "culture_time"]].min(axis=1)
    for column in ("antibiotic_time", "culture_time", "t_si"):
        pairs[column] = pairs[column].astype("datetime64[ns]")
    return pairs[PAIR_COLUMNS].sort_values(
        ["subject_id", "hadm_id", "t_si", "delta_hours", "antibiotic_id", "culture_id"]
    ).reset_index(drop=True)
