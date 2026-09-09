"""Patient-clustered uncertainty for repeated-landmark predictions."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

from .modeling import binary_metrics


METRICS = ("auroc", "auprc", "brier", "log_loss")


def _validate_inputs(
    table: pd.DataFrame, probability: Sequence[float], name: str
) -> np.ndarray:
    missing = sorted({"subject_id", "outcome"} - set(table.columns))
    if missing:
        raise ValueError(f"table is missing columns: {', '.join(missing)}")
    values = np.asarray(probability, dtype=float)
    if len(values) != len(table):
        raise ValueError(f"{name} probabilities must align one-to-one with table")
    if not np.isfinite(values).all() or ((values < 0) | (values > 1)).any():
        raise ValueError(f"{name} probabilities must be finite and in [0, 1]")
    return values


def patient_cluster_bootstrap_comparison(
    table: pd.DataFrame,
    reference_probability: Sequence[float],
    candidate_probability: Sequence[float],
    *,
    replicates: int = 1000,
    seed: int = 20260909,
) -> pd.DataFrame:
    """Paired bootstrap differences after resampling complete patients.

    Differences are always candidate minus reference. Thus positive values are
    favorable for AUROC/AUPRC and unfavorable for Brier/log loss.
    """
    if replicates <= 0:
        raise ValueError("replicates must be positive")
    reference = _validate_inputs(table, reference_probability, "reference")
    candidate = _validate_inputs(table, candidate_probability, "candidate")
    subjects = table["subject_id"].drop_duplicates().to_numpy()
    if len(subjects) < 2:
        raise ValueError("at least two patients are required")
    positions = {
        subject: np.flatnonzero(table["subject_id"].to_numpy() == subject)
        for subject in subjects
    }
    rng = np.random.default_rng(seed)
    rows = []
    for replicate in range(1, replicates + 1):
        sampled = rng.choice(subjects, size=len(subjects), replace=True)
        index = np.concatenate([positions[subject] for subject in sampled])
        outcome = table["outcome"].to_numpy(int)[index]
        reference_metrics = binary_metrics(outcome, reference[index])
        candidate_metrics = binary_metrics(outcome, candidate[index])
        rows.append({
            "replicate": replicate,
            **{
                f"delta_{metric}": candidate_metrics[metric] - reference_metrics[metric]
                for metric in METRICS
            },
        })
    return pd.DataFrame(rows)


def percentile_intervals(
    bootstrap: pd.DataFrame,
    *,
    confidence_level: float = 0.95,
) -> pd.DataFrame:
    """Summarize finite bootstrap estimates with percentile intervals."""
    if not 0 < confidence_level < 1:
        raise ValueError("confidence_level must be in (0, 1)")
    columns = [column for column in bootstrap if column != "replicate"]
    if not columns:
        raise ValueError("bootstrap contains no metric columns")
    alpha = 1 - confidence_level
    rows = []
    for column in columns:
        values = pd.to_numeric(bootstrap[column], errors="coerce").dropna()
        rows.append({
            "metric": column,
            "estimate": float(values.median()) if len(values) else np.nan,
            "lower": float(values.quantile(alpha / 2)) if len(values) else np.nan,
            "upper": float(values.quantile(1 - alpha / 2)) if len(values) else np.nan,
            "successful_replicates": int(len(values)),
        })
    return pd.DataFrame(rows)
