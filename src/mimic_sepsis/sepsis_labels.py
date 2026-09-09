"""Leakage-aware integration of suspected infection with hourly SOFA.

The resulting phenotype is retrospective: ``t0`` estimates clinical onset,
whereas ``label_available_at`` records when both infection suspicion and organ
dysfunction have become observable.  Neither belongs in predictor features.
"""

from __future__ import annotations

from datetime import timedelta

import pandas as pd


PAIR_KEYS = ["subject_id", "hadm_id", "antibiotic_id", "culture_id"]
EPISODE_COLUMNS = [
    *PAIR_KEYS, "stay_id", "antibiotic_time", "culture_time", "t_si",
    "t_si_confirmed_at", "baseline_sofa", "baseline_time",
    "baseline_assumed_zero", "baseline_missing_components",
    "peak_acute_sofa", "peak_acute_time", "t0", "sofa_at_t0",
    "delta_sofa_at_t0", "missing_components_at_t0", "sepsis3",
    "label_available_at", "baseline_hour_count", "acute_hour_count",
    "acute_window_covered", "exclusion_reason",
]


def _require(frame: pd.DataFrame, columns: set[str], name: str) -> None:
    missing = sorted(columns - set(frame.columns))
    if missing:
        raise ValueError(f"{name} is missing columns: {', '.join(missing)}")


def build_sepsis_episodes(
    pairs: pd.DataFrame,
    icustays: pd.DataFrame,
    sofa_hourly: pd.DataFrame,
    *,
    baseline_hours: int = 48,
    acute_hours_before: int = 24,
    acute_hours_after: int = 24,
    delta_threshold: int = 2,
) -> pd.DataFrame:
    """Create one audited Sepsis-3 result per infection-pair/stay candidate.

    Baseline is the minimum observed hourly ``sofa_total`` in
    ``[t_si-baseline_hours, t_si)``.  If no baseline hour exists it is assumed
    to be zero and explicitly flagged.  Acute hours include both endpoints.
    """
    _require(
        pairs,
        set(PAIR_KEYS) | {"antibiotic_time", "culture_time", "t_si"},
        "pairs",
    )
    _require(
        icustays,
        {"subject_id", "hadm_id", "stay_id", "intime", "outtime"},
        "icustays",
    )
    _require(
        sofa_hourly,
        {"stay_id", "endtime", "sofa_total", "missing_components"},
        "sofa_hourly",
    )
    if min(baseline_hours, acute_hours_before, acute_hours_after) < 0:
        raise ValueError("Phenotype windows must be non-negative")
    if baseline_hours == 0 or delta_threshold < 0:
        raise ValueError("baseline_hours must be positive and threshold non-negative")
    if pairs.empty:
        return pd.DataFrame(columns=EPISODE_COLUMNS)

    pairs = pairs.copy()
    stays = icustays.copy()
    sofa = sofa_hourly.copy()
    for column in ["antibiotic_time", "culture_time", "t_si"]:
        pairs[column] = pd.to_datetime(pairs[column], errors="coerce", format="mixed")
    for column in ["intime", "outtime"]:
        stays[column] = pd.to_datetime(stays[column], errors="coerce", format="mixed")
    sofa["endtime"] = pd.to_datetime(sofa["endtime"], errors="coerce", format="mixed")
    if pairs[PAIR_KEYS].duplicated().any():
        raise ValueError("pairs must be unique by source identifiers")
    if stays["stay_id"].duplicated().any():
        raise ValueError("icustays must be unique by stay_id")
    if sofa.duplicated(["stay_id", "endtime"]).any():
        raise ValueError("sofa_hourly must be unique by stay_id and endtime")
    if pairs[["antibiotic_time", "culture_time", "t_si"]].isna().any(axis=None):
        raise ValueError("pairs contains invalid timestamps")
    expected_t_si = pairs[["antibiotic_time", "culture_time"]].min(axis=1)
    if not pairs["t_si"].eq(expected_t_si).all():
        raise ValueError("t_si must equal the earlier antibiotic/culture time")

    pairs["t_si_confirmed_at"] = pairs[["antibiotic_time", "culture_time"]].max(axis=1)
    pairs["acute_start"] = pairs["t_si"] - pd.to_timedelta(acute_hours_before, unit="h")
    pairs["acute_end"] = pairs["t_si"] + pd.to_timedelta(acute_hours_after, unit="h")
    candidates = pairs.merge(
        stays[["subject_id", "hadm_id", "stay_id", "intime", "outtime"]],
        on=["subject_id", "hadm_id"], how="left", validate="many_to_many",
    )
    overlap = candidates["stay_id"].notna() & candidates["intime"].lt(
        candidates["acute_end"]
    ) & candidates["outtime"].gt(candidates["acute_start"])

    results: list[dict] = []
    overlapping_keys: set[tuple] = set()
    for row in candidates.loc[overlap].itertuples(index=False):
        pair_key = tuple(getattr(row, key) for key in PAIR_KEYS)
        overlapping_keys.add(pair_key)
        hours = sofa.loc[sofa["stay_id"].eq(row.stay_id)].sort_values("endtime")
        baseline_start = row.t_si - timedelta(hours=baseline_hours)
        baseline = hours.loc[
            hours["endtime"].ge(baseline_start) & hours["endtime"].lt(row.t_si)
        ].dropna(subset=["sofa_total"])
        acute = hours.loc[
            hours["endtime"].ge(row.acute_start)
            & hours["endtime"].le(row.acute_end)
        ].dropna(subset=["sofa_total"])

        baseline_assumed = baseline.empty
        if baseline_assumed:
            baseline_sofa, baseline_time, baseline_missing = 0, pd.NaT, pd.NA
        else:
            baseline_sofa = int(baseline["sofa_total"].min())
            baseline_row = baseline.loc[baseline["sofa_total"].eq(baseline_sofa)].iloc[0]
            baseline_time = baseline_row["endtime"]
            baseline_missing = int(baseline_row["missing_components"])

        if acute.empty:
            peak_sofa = peak_time = t0 = sofa_at_t0 = delta_at_t0 = missing_at_t0 = pd.NA
            sepsis3 = False
            exclusion_reason = "no_acute_sofa_hours"
        else:
            peak_sofa = int(acute["sofa_total"].max())
            peak_row = acute.loc[acute["sofa_total"].eq(peak_sofa)].iloc[0]
            peak_time = peak_row["endtime"]
            qualifying = acute.loc[(acute["sofa_total"] - baseline_sofa).ge(delta_threshold)]
            sepsis3 = not qualifying.empty
            if sepsis3:
                onset = qualifying.iloc[0]
                t0 = onset["endtime"]
                sofa_at_t0 = int(onset["sofa_total"])
                delta_at_t0 = sofa_at_t0 - baseline_sofa
                missing_at_t0 = int(onset["missing_components"])
            else:
                t0 = sofa_at_t0 = delta_at_t0 = missing_at_t0 = pd.NA
            exclusion_reason = pd.NA

        full_coverage = (
            not hours.empty
            and hours["endtime"].min() <= row.acute_start
            and hours["endtime"].max() >= row.acute_end
        )
        result = {key: getattr(row, key) for key in PAIR_KEYS}
        result.update({
            "stay_id": row.stay_id,
            "antibiotic_time": row.antibiotic_time,
            "culture_time": row.culture_time,
            "t_si": row.t_si,
            "t_si_confirmed_at": row.t_si_confirmed_at,
            "baseline_sofa": baseline_sofa,
            "baseline_time": baseline_time,
            "baseline_assumed_zero": baseline_assumed,
            "baseline_missing_components": baseline_missing,
            "peak_acute_sofa": peak_sofa,
            "peak_acute_time": peak_time,
            "t0": t0,
            "sofa_at_t0": sofa_at_t0,
            "delta_sofa_at_t0": delta_at_t0,
            "missing_components_at_t0": missing_at_t0,
            "sepsis3": sepsis3,
            "label_available_at": max(t0, row.t_si_confirmed_at) if sepsis3 else pd.NaT,
            "baseline_hour_count": len(baseline),
            "acute_hour_count": len(acute),
            "acute_window_covered": full_coverage,
            "exclusion_reason": exclusion_reason,
        })
        results.append(result)

    for row in pairs.itertuples(index=False):
        pair_key = tuple(getattr(row, key) for key in PAIR_KEYS)
        if pair_key in overlapping_keys:
            continue
        result = {column: pd.NA for column in EPISODE_COLUMNS}
        result.update({key: getattr(row, key) for key in PAIR_KEYS})
        result.update({
            "antibiotic_time": row.antibiotic_time,
            "culture_time": row.culture_time,
            "t_si": row.t_si,
            "t_si_confirmed_at": max(row.antibiotic_time, row.culture_time),
            "baseline_assumed_zero": False,
            "sepsis3": False,
            "acute_window_covered": False,
            "baseline_hour_count": 0,
            "acute_hour_count": 0,
            "exclusion_reason": "no_overlapping_icu_stay",
        })
        results.append(result)

    output = pd.DataFrame(results, columns=EPISODE_COLUMNS)
    output["sepsis3"] = output["sepsis3"].astype(bool)
    output["baseline_assumed_zero"] = output["baseline_assumed_zero"].astype(bool)
    output["acute_window_covered"] = output["acute_window_covered"].astype(bool)
    return output.sort_values(PAIR_KEYS + ["stay_id"], na_position="last").reset_index(drop=True)


def first_sepsis_episode_per_stay(episodes: pd.DataFrame) -> pd.DataFrame:
    """Select the first qualifying onset per stay with deterministic ties."""
    _require(episodes, set(EPISODE_COLUMNS), "episodes")
    qualifying = episodes.loc[episodes["sepsis3"] & episodes["stay_id"].notna()].copy()
    if qualifying.empty:
        return qualifying
    return (
        qualifying.sort_values(
            ["stay_id", "t0", "t_si", "antibiotic_id", "culture_id"],
            kind="stable",
        )
        .drop_duplicates("stay_id", keep="first")
        .reset_index(drop=True)
    )
