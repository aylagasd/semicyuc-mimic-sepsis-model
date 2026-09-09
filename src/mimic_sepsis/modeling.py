"""Leakage-safe assembly, fitting and grouped validation utilities."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


MODEL_KEYS = ["subject_id", "hadm_id", "stay_id", "landmark_time"]


def _require(frame: pd.DataFrame, columns: set[str], name: str) -> None:
    missing = sorted(columns - set(frame.columns))
    if missing:
        raise ValueError(f"{name} is missing columns: {', '.join(missing)}")


def assemble_modeling_table(
    landmarks: pd.DataFrame,
    features: pd.DataFrame,
    *,
    horizon_hours: int = 6,
) -> pd.DataFrame:
    """Join observed outcomes to predictor-only rows for one future horizon."""
    _require(
        landmarks,
        set(MODEL_KEYS) | {"horizon_hours", "horizon_observed", "outcome"},
        "landmarks",
    )
    _require(features, set(MODEL_KEYS), "features")
    if horizon_hours <= 0:
        raise ValueError("horizon_hours must be positive")
    if features.duplicated(["stay_id", "landmark_time"]).any():
        raise ValueError("features must be unique by stay_id and landmark_time")
    selected = landmarks.loc[
        landmarks["horizon_hours"].eq(horizon_hours)
        & landmarks["horizon_observed"].eq(True)
    ].copy()
    if selected["outcome"].isna().any():
        raise ValueError("observed landmarks cannot have missing outcomes")
    result = selected.merge(features, on=MODEL_KEYS, how="left", validate="one_to_one")
    feature_columns = [column for column in features if column not in MODEL_KEYS]
    if result[feature_columns].isna().all(axis=1).any():
        raise ValueError("at least one observed landmark has no matching feature row")
    result["outcome"] = result["outcome"].astype("int8")
    return result.sort_values(["subject_id", "stay_id", "landmark_time"]).reset_index(drop=True)


def equal_patient_weights(table: pd.DataFrame) -> np.ndarray:
    """Give every patient equal total influence while keeping mean weight one."""
    _require(table, {"subject_id"}, "table")
    if table.empty:
        return np.array([], dtype=float)
    counts = table.groupby("subject_id")["subject_id"].transform("size").to_numpy(float)
    return len(table) / (table["subject_id"].nunique() * counts)


def patient_weighted_event_rate(table: pd.DataFrame) -> float:
    """Estimate event rate after equalizing total contribution per patient."""
    _require(table, {"subject_id", "outcome"}, "table")
    if table.empty:
        raise ValueError("table cannot be empty")
    return float(np.average(table["outcome"].to_numpy(float), weights=equal_patient_weights(table)))


def make_logistic_pipeline(
    feature_columns: Sequence[str],
    *,
    c: float = 1.0,
    elastic_net_l1_ratio: float | None = None,
    seed: int = 20260909,
) -> Pipeline:
    """Create a fold-local imputation/scaling/logistic-regression pipeline."""
    columns = list(feature_columns)
    if not columns or len(columns) != len(set(columns)):
        raise ValueError("feature_columns must be non-empty and unique")
    if c <= 0:
        raise ValueError("c must be positive")
    if elastic_net_l1_ratio is not None and not 0 <= elastic_net_l1_ratio <= 1:
        raise ValueError("elastic_net_l1_ratio must be in [0, 1]")
    preprocess = ColumnTransformer(
        [("numeric", Pipeline([
            ("impute", SimpleImputer(strategy="median", keep_empty_features=True)),
            ("scale", StandardScaler()),
        ]), columns)],
        remainder="drop",
        verbose_feature_names_out=False,
    )
    model = LogisticRegression(
        C=c,
        solver="saga" if elastic_net_l1_ratio is not None else "lbfgs",
        l1_ratio=0 if elastic_net_l1_ratio is None else elastic_net_l1_ratio,
        max_iter=5000,
        random_state=seed,
    )
    return Pipeline([("preprocess", preprocess), ("model", model)])


def binary_metrics(y_true: Sequence[int], probability: Sequence[float]) -> dict[str, float]:
    """Return probability metrics; undefined discrimination is explicit NaN."""
    y = np.asarray(y_true, dtype=int)
    p = np.asarray(probability, dtype=float)
    if len(y) == 0 or len(y) != len(p):
        raise ValueError("outcomes and probabilities must have equal non-zero length")
    if not np.isfinite(p).all() or ((p < 0) | (p > 1)).any():
        raise ValueError("probabilities must be finite and in [0, 1]")
    two_classes = np.unique(y).size == 2
    return {
        "n": float(len(y)),
        "events": float(y.sum()),
        "prevalence": float(y.mean()),
        "auroc": float(roc_auc_score(y, p)) if two_classes else np.nan,
        "auprc": float(average_precision_score(y, p)) if two_classes else np.nan,
        "brier": float(brier_score_loss(y, p)),
        "log_loss": float(log_loss(y, p, labels=[0, 1])),
    }


def grouped_cross_validation(
    table: pd.DataFrame,
    pipeline: Pipeline,
    feature_columns: Sequence[str],
    *,
    folds: int = 5,
    seed: int = 20260909,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Generate patient-disjoint out-of-fold predictions and fold metrics."""
    _require(table, {"subject_id", "outcome"} | set(feature_columns), "table")
    if folds < 2 or table["subject_id"].nunique() < folds:
        raise ValueError("folds must be >=2 and not exceed the number of patients")
    splitter = StratifiedGroupKFold(n_splits=folds, shuffle=True, random_state=seed)
    rows, metrics = [], []
    x = table[list(feature_columns)]
    y = table["outcome"].to_numpy(int)
    groups = table["subject_id"].to_numpy()
    for fold, (train_index, valid_index) in enumerate(splitter.split(x, y, groups), start=1):
        if set(groups[train_index]) & set(groups[valid_index]):
            raise AssertionError("patient leakage between cross-validation folds")
        if np.unique(y[train_index]).size < 2:
            raise ValueError(f"training fold {fold} contains one outcome class")
        fitted = clone(pipeline)
        fitted.fit(
            x.iloc[train_index], y[train_index],
            model__sample_weight=equal_patient_weights(table.iloc[train_index]),
        )
        probability = fitted.predict_proba(x.iloc[valid_index])[:, 1]
        fold_predictions = table.iloc[valid_index][MODEL_KEYS + ["outcome"]].copy()
        fold_predictions["fold"] = fold
        fold_predictions["probability"] = probability
        rows.append(fold_predictions)
        metrics.append({"fold": fold, **binary_metrics(y[valid_index], probability)})
    predictions = pd.concat(rows).sort_index()
    if len(predictions) != len(table):
        raise AssertionError("cross-validation did not predict every development row")
    return predictions.reset_index(drop=True), pd.DataFrame(metrics)


def grouped_prevalence_cross_validation(
    table: pd.DataFrame,
    *,
    folds: int = 5,
    seed: int = 20260909,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Generate leakage-safe fold-training prevalence predictions."""
    _require(table, set(MODEL_KEYS) | {"outcome"}, "table")
    if folds < 2 or table["subject_id"].nunique() < folds:
        raise ValueError("folds must be >=2 and not exceed the number of patients")
    splitter = StratifiedGroupKFold(n_splits=folds, shuffle=True, random_state=seed)
    x = np.zeros((len(table), 1))
    y = table["outcome"].to_numpy(int)
    groups = table["subject_id"].to_numpy()
    rows, metrics = [], []
    for fold, (train_index, valid_index) in enumerate(splitter.split(x, y, groups), start=1):
        probability = patient_weighted_event_rate(table.iloc[train_index])
        fold_predictions = table.iloc[valid_index][MODEL_KEYS + ["outcome"]].copy()
        fold_predictions["fold"] = fold
        fold_predictions["probability"] = probability
        rows.append(fold_predictions)
        metrics.append({
            "fold": fold,
            **binary_metrics(y[valid_index], np.repeat(probability, len(valid_index))),
        })
    predictions = pd.concat(rows).sort_index()
    return predictions.reset_index(drop=True), pd.DataFrame(metrics)
