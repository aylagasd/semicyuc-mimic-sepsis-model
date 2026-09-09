"""Aggregate, disclosure-conscious audits for the Sepsis-3 phenotype."""

from __future__ import annotations

import pandas as pd

from .sepsis_labels import first_sepsis_episode_per_stay


def pair_multiplicity(pairs: pd.DataFrame) -> pd.DataFrame:
    """Count admissions in prespecified pair-count bands."""
    required = {"hadm_id", "antibiotic_id", "culture_id"}
    missing = required - set(pairs.columns)
    if missing:
        raise ValueError(f"pairs is missing columns: {', '.join(sorted(missing))}")
    counts = pairs.groupby("hadm_id", dropna=False).size()
    bands = pd.cut(
        counts, bins=[0, 1, 4, 9, float("inf")],
        labels=["1", "2–4", "5–9", "≥10"], include_lowest=True,
    )
    result = bands.value_counts(sort=False).rename("admissions").reset_index()
    result.columns = ["pairs_per_admission", "admissions"]
    return result


def phenotype_summary(
    pairs: pd.DataFrame, episodes: pd.DataFrame, sepsis_stays: pd.DataFrame,
    shock_stays: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Return denominated counts without patient-level rows."""
    required = {
        "exclusion_reason", "baseline_assumed_zero", "acute_window_covered",
        "sepsis3", "stay_id",
    }
    missing = required - set(episodes.columns)
    if missing:
        raise ValueError(f"episodes is missing columns: {', '.join(sorted(missing))}")
    evaluable = episodes["exclusion_reason"].isna()
    observed_baseline = evaluable & ~episodes["baseline_assumed_zero"]
    sensitivity = first_sepsis_episode_per_stay(episodes.loc[observed_baseline])
    values = [
        ("infection_pairs", len(pairs), "pairs"),
        ("admissions_with_pairs", pairs["hadm_id"].nunique(), "admissions"),
        ("pair_stay_rows", len(episodes), "pair_stay_rows"),
        ("evaluable_pair_stay_rows", int(evaluable.sum()), "pair_stay_rows"),
        ("full_acute_coverage", int((evaluable & episodes["acute_window_covered"]).sum()), "pair_stay_rows"),
        ("sepsis3_stays_primary", len(sepsis_stays), "stays"),
        ("sepsis3_stays_observed_baseline", len(sensitivity), "stays"),
    ]
    if shock_stays is not None:
        if "septic_shock" not in shock_stays:
            raise ValueError("shock_stays is missing column: septic_shock")
        values.extend([
            ("septic_shock_proxy_stays", int(shock_stays["septic_shock"].sum()), "stays"),
            ("sepsis_stays_without_shock_proxy", int((~shock_stays["septic_shock"]).sum()), "stays"),
        ])
    return pd.DataFrame(values, columns=["metric", "count", "unit"])


def coverage_summary(episodes: pd.DataFrame) -> pd.DataFrame:
    """Summarize mutually exclusive episode evaluability categories."""
    reason = episodes["exclusion_reason"]
    category = pd.Series("partial_acute_window", index=episodes.index, dtype="string")
    category.loc[episodes["acute_window_covered"] & reason.isna()] = "full_acute_window"
    category.loc[reason.eq("no_acute_sofa_hours")] = "no_acute_sofa_hours"
    category.loc[reason.eq("no_overlapping_icu_stay")] = "no_overlapping_icu_stay"
    order = [
        "full_acute_window", "partial_acute_window", "no_acute_sofa_hours",
        "no_overlapping_icu_stay",
    ]
    result = category.value_counts().reindex(order, fill_value=0).rename("episodes").reset_index()
    result.columns = ["coverage", "episodes"]
    result["percent"] = (100 * result["episodes"] / len(episodes)).round(1) if len(episodes) else 0.0
    return result
