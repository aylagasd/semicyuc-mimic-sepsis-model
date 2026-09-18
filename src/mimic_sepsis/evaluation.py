"""Patient-clustered uncertainty for repeated-landmark predictions."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

from .modeling import binary_metrics


METRICS = ("auroc", "auprc", "brier", "log_loss")


def _binary_arrays(
    outcome: Sequence[int], probability: Sequence[float]
) -> tuple[np.ndarray, np.ndarray]:
    y = np.asarray(outcome, dtype=int)
    p = np.asarray(probability, dtype=float)
    if len(y) == 0 or len(y) != len(p):
        raise ValueError("outcomes and probabilities must have equal non-zero length")
    if not np.isin(y, [0, 1]).all():
        raise ValueError("outcomes must be binary")
    if not np.isfinite(p).all() or ((p < 0) | (p > 1)).any():
        raise ValueError("probabilities must be finite and in [0, 1]")
    return y, p


def _sigmoid(value: np.ndarray) -> np.ndarray:
    result = np.empty_like(value, dtype=float)
    positive = value >= 0
    result[positive] = 1 / (1 + np.exp(-value[positive]))
    exponent = np.exp(value[~positive])
    result[~positive] = exponent / (1 + exponent)
    return result


def calibration_metrics(
    outcome: Sequence[int], probability: Sequence[float], *, epsilon: float = 1e-6
) -> dict[str, float]:
    """Estimate calibration-in-the-large and logistic calibration slope.

    The intercept is fitted with the prediction logit as an offset. The slope
    is fitted jointly with a free intercept. Undefined or separated fits are
    returned as NaN rather than replaced with a finite value.
    """
    y, p = _binary_arrays(outcome, probability)
    if not 0 < epsilon < 0.5:
        raise ValueError("epsilon must be in (0, 0.5)")
    if np.unique(y).size < 2:
        return {
            "calibration_intercept": np.nan,
            "calibration_model_intercept": np.nan,
            "calibration_slope": np.nan,
        }
    logit = np.log(np.clip(p, epsilon, 1 - epsilon) / np.clip(1 - p, epsilon, 1))

    calibration_intercept = 0.0
    for _ in range(25):
        fitted_offset = _sigmoid(logit + calibration_intercept)
        information = float(np.sum(fitted_offset * (1 - fitted_offset)))
        if information <= 1e-12:
            calibration_intercept = np.nan
            break
        step = float(np.sum(y - fitted_offset) / information)
        calibration_intercept += step
        if not np.isfinite(calibration_intercept) or abs(calibration_intercept) > 50:
            calibration_intercept = np.nan
            break
        if abs(step) < 1e-10:
            break

    slope = np.nan
    free_intercept = np.nan
    if float(np.std(logit)) > 1e-12:
        design = np.column_stack([np.ones(len(y)), logit])
        coefficient = np.array([0.0, 1.0])
        converged = False
        for _ in range(100):
            fitted = _sigmoid(design @ coefficient)
            weights = np.clip(fitted * (1 - fitted), 1e-12, None)
            information = design.T @ (weights[:, None] * design)
            score = design.T @ (y - fitted)
            try:
                step = np.linalg.solve(information, score)
            except np.linalg.LinAlgError:
                break
            coefficient += step
            if not np.isfinite(coefficient).all() or np.max(np.abs(coefficient)) > 50:
                break
            if np.max(np.abs(step)) < 1e-8:
                converged = True
                break
        if converged:
            free_intercept, slope = (float(value) for value in coefficient)
    return {
        "calibration_intercept": float(calibration_intercept),
        "calibration_model_intercept": float(free_intercept),
        "calibration_slope": float(slope),
    }


def threshold_metrics(
    outcome: Sequence[int], probability: Sequence[float], *, threshold: float
) -> dict[str, float]:
    """Return classification and alert-burden metrics at a fixed threshold."""
    y, p = _binary_arrays(outcome, probability)
    if not 0 < threshold < 1:
        raise ValueError("threshold must be in (0, 1)")
    predicted = p >= threshold
    positive = y == 1
    tp = int(np.sum(predicted & positive))
    fp = int(np.sum(predicted & ~positive))
    tn = int(np.sum(~predicted & ~positive))
    fn = int(np.sum(~predicted & positive))

    def ratio(numerator: float, denominator: float) -> float:
        return float(numerator / denominator) if denominator else np.nan

    sensitivity = ratio(tp, tp + fn)
    specificity = ratio(tn, tn + fp)
    return {
        "threshold": float(threshold),
        "tp": float(tp), "fp": float(fp), "tn": float(tn), "fn": float(fn),
        "sensitivity": sensitivity,
        "specificity": specificity,
        "ppv": ratio(tp, tp + fp),
        "npv": ratio(tn, tn + fn),
        "lr_positive": ratio(sensitivity, 1 - specificity),
        "lr_negative": ratio(1 - sensitivity, specificity),
        "alert_fraction": float(predicted.mean()),
    }


def decision_curve(
    outcome: Sequence[int],
    probability: Sequence[float],
    *,
    thresholds: Sequence[float],
) -> pd.DataFrame:
    """Calculate model, treat-all and treat-none net benefit per landmark."""
    y, p = _binary_arrays(outcome, probability)
    values = np.asarray(tuple(thresholds), dtype=float)
    if len(values) == 0 or not np.isfinite(values).all():
        raise ValueError("thresholds must be a non-empty finite sequence")
    if ((values <= 0) | (values >= 1)).any() or len(np.unique(values)) != len(values):
        raise ValueError("thresholds must be unique and in (0, 1)")
    prevalence = float(y.mean())
    rows = []
    for threshold in values:
        predicted = p >= threshold
        tp_rate = float(np.mean(predicted & (y == 1)))
        fp_rate = float(np.mean(predicted & (y == 0)))
        odds = threshold / (1 - threshold)
        rows.extend([
            {"threshold": threshold, "strategy": "model",
             "net_benefit": tp_rate - fp_rate * odds},
            {"threshold": threshold, "strategy": "treat_all",
             "net_benefit": prevalence - (1 - prevalence) * odds},
            {"threshold": threshold, "strategy": "treat_none", "net_benefit": 0.0},
        ])
    return pd.DataFrame(rows)


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


def patient_cluster_bootstrap_estimates(
    table: pd.DataFrame,
    probability: Sequence[float],
    *,
    replicates: int = 1000,
    seed: int = 20260909,
) -> pd.DataFrame:
    """Bootstrap absolute discrimination, accuracy and calibration estimates."""
    if replicates <= 0:
        raise ValueError("replicates must be positive")
    values = _validate_inputs(table, probability, "model")
    subjects = table["subject_id"].drop_duplicates().to_numpy()
    if len(subjects) < 2:
        raise ValueError("at least two patients are required")
    positions = {
        subject: np.flatnonzero(table["subject_id"].to_numpy() == subject)
        for subject in subjects
    }
    outcome = table["outcome"].to_numpy(int)
    rng = np.random.default_rng(seed)
    rows = []
    for replicate in range(1, replicates + 1):
        sampled = rng.choice(subjects, size=len(subjects), replace=True)
        index = np.concatenate([positions[subject] for subject in sampled])
        rows.append({
            "replicate": replicate,
            **binary_metrics(outcome[index], values[index]),
            **calibration_metrics(outcome[index], values[index]),
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
