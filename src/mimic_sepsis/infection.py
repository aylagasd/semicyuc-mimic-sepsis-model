"""Temporal pairing primitives for the suspected-infection phenotype."""

from __future__ import annotations

import pandas as pd


PAIR_COLUMNS = [
    "subject_id", "hadm_id", "antibiotic_id", "antibiotic_time",
    "culture_id", "culture_time", "pair_direction", "delta_hours", "t_si",
]


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
    return pairs[PAIR_COLUMNS].sort_values(
        ["subject_id", "hadm_id", "t_si", "delta_hours", "antibiotic_id", "culture_id"]
    ).reset_index(drop=True)
