"""Aggregate, disclosure-conscious audits for the Sepsis-3 phenotype.

The functions in this module deliberately return denominated aggregate tables.
They support protocol review; they never change a decision status or select a
definition from observed results.
"""

from __future__ import annotations

import pandas as pd

from .sepsis_labels import first_sepsis_episode_per_stay


def _require(frame: pd.DataFrame, columns: set[str], name: str) -> None:
    missing = sorted(columns - set(frame.columns))
    if missing:
        raise ValueError(f"{name} is missing columns: {', '.join(missing)}")


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


def infection_timing_summary(pairs: pd.DataFrame) -> pd.DataFrame:
    """Summarize the ordering of antimicrobial and culture evidence."""
    _require(pairs, {"hadm_id", "pair_direction"}, "pairs")
    order = ["antibiotic_first", "culture_first", "simultaneous"]
    counts = pairs["pair_direction"].astype("string").value_counts()
    unknown = int((~pairs["pair_direction"].astype("string").isin(order)).sum())
    rows = [(name, int(counts.get(name, 0))) for name in order]
    rows.append(("unknown", unknown))
    result = pd.DataFrame(rows, columns=["pair_direction", "pairs"])
    denominator = len(pairs)
    result["percent_of_pairs"] = (
        100 * result["pairs"] / denominator if denominator else 0.0
    )
    return result


def infection_evidence_sensitivity_summary(
    primary_pairs: pd.DataFrame,
    primary_stays: pd.DataFrame,
    sensitivity_pairs: pd.DataFrame,
    sensitivity_stays: pd.DataFrame,
) -> pd.DataFrame:
    """Compare recomputed infection-evidence variants with the primary labels."""
    _require(primary_pairs, {"hadm_id"}, "primary_pairs")
    _require(primary_stays, {"stay_id"}, "primary_stays")
    _require(
        sensitivity_pairs, {"sensitivity", "hadm_id"}, "sensitivity_pairs"
    )
    _require(
        sensitivity_stays, {"sensitivity", "stay_id"}, "sensitivity_stays"
    )
    pair_names = list(sensitivity_pairs["sensitivity"].drop_duplicates())
    stay_names = list(sensitivity_stays["sensitivity"].drop_duplicates())
    if not pair_names or not set(stay_names).issubset(pair_names):
        raise ValueError(
            "Infection sensitivity stays contain an unknown variant"
        )
    if primary_stays["stay_id"].duplicated().any():
        raise ValueError("primary_stays must contain at most one row per stay")
    primary_stay_ids = set(primary_stays["stay_id"])
    rows = []
    for name in pair_names:
        pairs = sensitivity_pairs.loc[sensitivity_pairs["sensitivity"].eq(name)]
        stays = sensitivity_stays.loc[sensitivity_stays["sensitivity"].eq(name)]
        if stays["stay_id"].duplicated().any():
            raise ValueError(
                f"Infection sensitivity {name!r} contains duplicate stays"
            )
        stay_ids = set(stays["stay_id"])
        rows.append({
            "sensitivity": str(name),
            "infection_pairs": len(pairs),
            "admissions_with_pairs": pairs["hadm_id"].nunique(),
            "sepsis3_stays": len(stays),
            "delta_pairs_vs_primary": len(pairs) - len(primary_pairs),
            "delta_sepsis3_stays_vs_primary": len(stays) - len(primary_stays),
            "primary_sepsis3_stays_retained": len(stay_ids & primary_stay_ids),
            "new_sepsis3_stays_vs_primary": len(stay_ids - primary_stay_ids),
            "available": True,
        })
    return pd.DataFrame(rows)


def unavailable_infection_evidence_sensitivities() -> pd.DataFrame:
    """Represent runs that predate materialized D004 sensitivities."""
    return pd.DataFrame([{
        "sensitivity": "not_available",
        "infection_pairs": None,
        "admissions_with_pairs": None,
        "sepsis3_stays": None,
        "delta_pairs_vs_primary": None,
        "delta_sepsis3_stays_vs_primary": None,
        "primary_sepsis3_stays_retained": None,
        "new_sepsis3_stays_vs_primary": None,
        "available": False,
    }])


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
    _require(episodes, {"acute_window_covered", "exclusion_reason"}, "episodes")
    reason = episodes["exclusion_reason"]
    allowed_reasons = {"no_acute_sofa_hours", "no_overlapping_icu_stay"}
    unexpected = sorted(set(reason.dropna().astype(str)) - allowed_reasons)
    if unexpected:
        raise ValueError(
            "episodes contains unexpected exclusion reasons: "
            + ", ".join(unexpected)
        )
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


def coverage_sensitivity_summary(episodes: pd.DataFrame) -> pd.DataFrame:
    """Compare predeclared D011 eligibility sensitivities without choosing one.

    Counts of Sepsis-3 stays are recalculated after applying each eligibility
    rule: a stay is positive if it retains at least one qualifying pair. This
    table is descriptive evidence for protocol review, not an automatic
    optimization criterion.
    """
    _require(
        episodes,
        {
            "stay_id", "sepsis3", "exclusion_reason",
            "baseline_assumed_zero", "acute_window_covered",
        },
        "episodes",
    )
    evaluable = episodes["exclusion_reason"].isna()
    rules = [
        ("primary_no_coverage_exclusion", evaluable),
        ("baseline_observed", evaluable & ~episodes["baseline_assumed_zero"]),
        ("full_acute_window", evaluable & episodes["acute_window_covered"]),
        (
            "baseline_observed_and_full_acute_window",
            evaluable
            & ~episodes["baseline_assumed_zero"]
            & episodes["acute_window_covered"],
        ),
    ]
    rows = []
    for name, mask in rules:
        eligible = episodes.loc[mask]
        positive = eligible.loc[eligible["sepsis3"]]
        rows.append({
            "sensitivity": name,
            "eligible_pair_stay_rows": len(eligible),
            "eligible_stays": eligible["stay_id"].nunique(),
            "positive_pair_stay_rows": len(positive),
            "sepsis3_stays": positive["stay_id"].nunique(),
        })
    return pd.DataFrame(rows)


def complete_sofa_sensitivity_summary(episodes: pd.DataFrame) -> pd.DataFrame:
    """Summarize episodes fully recomputed with ``sofa_complete``."""
    result = coverage_sensitivity_summary(episodes).copy()
    names = {
        "primary_no_coverage_exclusion": "complete_sofa",
        "baseline_observed": "complete_sofa_and_observed_baseline",
        "full_acute_window": "complete_sofa_and_full_acute_window",
        "baseline_observed_and_full_acute_window": (
            "complete_sofa_observed_baseline_and_full_acute_window"
        ),
    }
    result["sensitivity"] = result["sensitivity"].map(names)
    result.insert(1, "available", True)
    return result


def unavailable_complete_sofa_sensitivity() -> pd.DataFrame:
    """Return an explicit, typed marker for legacy runs lacking the artifact."""
    result = pd.DataFrame({
        "sensitivity": ["complete_sofa_artifact_missing"],
        "available": [False],
        "eligible_pair_stay_rows": pd.array([pd.NA], dtype="Int64"),
        "eligible_stays": pd.array([pd.NA], dtype="Int64"),
        "positive_pair_stay_rows": pd.array([pd.NA], dtype="Int64"),
        "sepsis3_stays": pd.array([pd.NA], dtype="Int64"),
    })
    return result


def sofa_completeness_summary(sepsis_stays: pd.DataFrame) -> pd.DataFrame:
    """Describe missing SOFA components at each primary Sepsis-3 onset.

    This is not the six-complete-components sensitivity itself. That analysis
    must recompute the first qualifying crossing from hourly SOFA rather than
    filter already selected onsets.
    """
    _require(
        sepsis_stays,
        {"stay_id", "sepsis3", "missing_components_at_t0"},
        "sepsis_stays",
    )
    if sepsis_stays["stay_id"].duplicated().any():
        raise ValueError("sepsis_stays must contain at most one row per stay_id")
    positive = sepsis_stays.loc[sepsis_stays["sepsis3"]].copy()
    missing = pd.to_numeric(positive["missing_components_at_t0"], errors="coerce")
    category = pd.Series("unavailable", index=positive.index, dtype="string")
    category.loc[missing.eq(0)] = "0_complete"
    category.loc[missing.eq(1)] = "1_missing"
    category.loc[missing.between(2, 3, inclusive="both")] = "2_to_3_missing"
    category.loc[missing.between(4, 6, inclusive="both")] = "4_to_6_missing"
    positive["component_missingness"] = category
    order = [
        "0_complete", "1_missing", "2_to_3_missing", "4_to_6_missing",
        "unavailable",
    ]
    grouped = positive.groupby("component_missingness", observed=False)
    rows = []
    for label in order:
        if label in grouped.groups:
            group = grouped.get_group(label)
        else:
            group = positive.iloc[0:0]
        rows.append({
            "component_missingness": label,
            "sepsis3_stays": len(group),
        })
    result = pd.DataFrame(rows)
    denominator = len(positive)
    result["percent_of_sepsis3_stays"] = (
        100 * result["sepsis3_stays"] / denominator
        if denominator else 0.0
    )
    return result


def shock_proxy_summary(shock_stays: pd.DataFrame) -> pd.DataFrame:
    """Audit shock-proxy classification and the fluid-verification limitation."""
    _require(
        shock_stays,
        {"septic_shock", "adequate_fluids_verified"},
        "shock_stays",
    )
    shock = shock_stays["septic_shock"].fillna(False).astype(bool)
    fluids = shock_stays["adequate_fluids_verified"].fillna(False).astype(bool)
    rows = [
        ("sepsis3_stays_evaluated", len(shock_stays), "stays"),
        ("shock_proxy_positive", int(shock.sum()), "stays"),
        ("shock_proxy_negative", int((~shock).sum()), "stays"),
        ("adequate_fluids_verified", int(fluids.sum()), "stays"),
        ("adequate_fluids_not_verified", int((~fluids).sum()), "stays"),
    ]
    return pd.DataFrame(rows, columns=["metric", "count", "unit"])


def shock_concurrency_sensitivity_summary(
    shock_stays: pd.DataFrame,
    sensitivities: pd.DataFrame,
) -> pd.DataFrame:
    """Compare recomputed concurrency-window labels with the primary proxy."""
    _require(shock_stays, {"stay_id", "septic_shock"}, "shock_stays")
    _require(
        sensitivities,
        {"sensitivity", "concurrency_hours", "stay_id", "septic_shock"},
        "sensitivities",
    )
    if shock_stays["stay_id"].duplicated().any():
        raise ValueError("shock_stays must contain at most one row per stay")
    primary = shock_stays[["stay_id", "septic_shock"]].copy()
    primary["septic_shock"] = primary["septic_shock"].fillna(False).astype(bool)
    primary_positive = int(primary["septic_shock"].sum())
    rows = []
    for name, variant in sensitivities.groupby("sensitivity", sort=False):
        if variant["stay_id"].duplicated().any() or set(variant["stay_id"]) != set(
            primary["stay_id"]
        ):
            raise ValueError(
                f"Shock sensitivity {name!r} does not evaluate every primary stay once"
            )
        hours = pd.to_numeric(variant["concurrency_hours"], errors="raise")
        if hours.nunique() != 1:
            raise ValueError(f"Shock sensitivity {name!r} has inconsistent windows")
        comparison = primary.merge(
            variant[["stay_id", "septic_shock"]],
            on="stay_id",
            how="inner",
            suffixes=("_primary", "_sensitivity"),
            validate="one_to_one",
        )
        sensitivity_positive = comparison["septic_shock_sensitivity"].fillna(
            False
        ).astype(bool)
        agreement = comparison["septic_shock_primary"].eq(sensitivity_positive)
        rows.append({
            "sensitivity": str(name),
            "concurrency_hours": float(hours.iloc[0]),
            "evaluated_stays": len(comparison),
            "shock_proxy_positive": int(sensitivity_positive.sum()),
            "delta_positive_vs_primary": int(sensitivity_positive.sum())
            - primary_positive,
            "agreement_with_primary": int(agreement.sum()),
            "percent_agreement": (
                100 * float(agreement.mean()) if len(comparison) else None
            ),
            "available": True,
        })
    if not rows:
        raise ValueError("Shock concurrency sensitivity artifact is empty")
    return pd.DataFrame(rows)


def unavailable_shock_concurrency_sensitivities() -> pd.DataFrame:
    """Represent legacy runs that predate materialized D010 sensitivities."""
    return pd.DataFrame([{
        "sensitivity": "not_available",
        "concurrency_hours": None,
        "evaluated_stays": None,
        "shock_proxy_positive": None,
        "delta_positive_vs_primary": None,
        "agreement_with_primary": None,
        "percent_agreement": None,
        "available": False,
    }])


def decision_evidence_summary(
    *, complete_sofa_available: bool = False,
    shock_sensitivity_available: bool = False,
    infection_sensitivity_available: bool = False,
) -> pd.DataFrame:
    """Declare what one primary phenotype run can and cannot resolve."""
    return pd.DataFrame([
        {
            "decision_id": "D002",
            "evidence_in_report": "not_comparative",
            "remaining_requirement": (
                "rebuild all prespecified cohort-policy variants and compare "
                "aggregate flow"
            ),
        },
        {
            "decision_id": "D004",
            "evidence_in_report": (
                "quantitative_prescription_start_sensitivity"
                if infection_sensitivity_available
                else "descriptive_only"
            ),
            "remaining_requirement": (
                "clinical review of the versioned antimicrobial list and "
                "decisions on expanded cultures, pairing windows and "
                "perioperative exclusions"
            ),
        },
        {
            "decision_id": "D010",
            "evidence_in_report": (
                "quantitative_concurrency_sensitivities"
                if shock_sensitivity_available
                else "descriptive_only"
            ),
            "remaining_requirement": (
                "clinical acceptance of the EHR proxy, explicit absence of "
                "verified adequate fluid resuscitation, and decisions on MAP, "
                "fluids and the restrictive vasopressor list"
            ),
        },
        {
            "decision_id": "D011",
            "evidence_in_report": (
                "quantitative_coverage_and_complete_sofa_sensitivities"
                if complete_sofa_available
                else "quantitative_coverage_sensitivities"
            ),
            "remaining_requirement": (
                "clinical/statistical sign-off without optimizing on demo or "
                "locked test data"
                if complete_sofa_available
                else "recompute the six-complete-components sensitivity from "
                "hourly SOFA, then obtain clinical/statistical sign-off without "
                "optimizing on demo or locked test data"
            ),
        },
    ])
