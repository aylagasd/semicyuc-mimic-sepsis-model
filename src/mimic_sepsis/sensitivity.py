"""Prespecified sensitivity summaries using development/validation only."""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

from .cohort import StayPolicy, build_adult_icu_cohort
from .modeling import (
    assemble_modeling_table,
    binary_metrics,
    equal_patient_weights,
    grouped_cross_validation,
    make_logistic_pipeline,
)


def feature_columns_for_window(
    primary_columns: Sequence[str], *, primary_window: int = 24, window: int
) -> list[str]:
    """Map a predeclared feature set to an alternative lookback suffix."""
    if primary_window <= 0 or window <= 0:
        raise ValueError("windows must be positive")
    suffix = f"_{primary_window}h"
    columns = list(primary_columns)
    if not columns or any(not column.endswith(suffix) for column in columns):
        raise ValueError(f"all columns must end in {suffix}")
    return [f"{column[:-len(suffix)]}_{window}h" for column in columns]


def cohort_policy_summary(
    patients: pd.DataFrame,
    admissions: pd.DataFrame,
    icustays: pd.DataFrame,
    *,
    policies: Sequence[str] = (
        StayPolicy.FIRST_PER_ADMISSION,
        StayPolicy.FIRST_PER_PATIENT,
        StayPolicy.ALL,
    ),
) -> pd.DataFrame:
    """Compare aggregate cohort flow under explicitly named stay policies."""
    rows = []
    for raw_policy in policies:
        policy = StayPolicy(raw_policy)
        result = build_adult_icu_cohort(
            patients, admissions, icustays, stay_policy=policy
        )
        rows.append({"policy": policy.value, **result.flow})
    return pd.DataFrame(rows)


def feature_coverage_grid(
    features: pd.DataFrame,
    *,
    variables: Sequence[str],
    lookbacks_hours: Sequence[int],
) -> pd.DataFrame:
    """Summarize measurement availability without exposing landmark rows."""
    rows = []
    for variable in variables:
        for hours in lookbacks_hours:
            column = f"{variable}_missing_{hours}h"
            if column not in features:
                raise ValueError(f"features is missing column: {column}")
            observed = int((~features[column].astype(bool)).sum())
            rows.append({
                "variable": variable,
                "lookback_hours": int(hours),
                "landmarks": len(features),
                "observed": observed,
                "percent_observed": 100 * observed / len(features) if len(features) else float("nan"),
            })
    return pd.DataFrame(rows)


def evaluate_horizon_lookback_grid(
    development_landmarks: pd.DataFrame,
    validation_landmarks: pd.DataFrame,
    development_features: pd.DataFrame,
    validation_features: pd.DataFrame,
    *,
    primary_columns: Sequence[str],
    horizons_hours: Sequence[int],
    lookbacks_hours: Sequence[int],
    folds: int,
    c: float,
    seed: int,
) -> pd.DataFrame:
    """Fit identical clinical baselines over a prespecified horizon/lookback grid."""
    rows = []
    for horizon in horizons_hours:
        development = assemble_modeling_table(
            development_landmarks, development_features, horizon_hours=int(horizon)
        )
        validation = assemble_modeling_table(
            validation_landmarks, validation_features, horizon_hours=int(horizon)
        )
        for lookback in lookbacks_hours:
            columns = feature_columns_for_window(primary_columns, window=int(lookback))
            pipeline = make_logistic_pipeline(columns, c=c, seed=seed)
            oof, _ = grouped_cross_validation(
                development, pipeline, columns, folds=folds, seed=seed
            )
            pipeline.fit(
                development[columns], development["outcome"],
                model__sample_weight=equal_patient_weights(development),
            )
            validation_probability = pipeline.predict_proba(validation[columns])[:, 1]
            for sample, outcome, probability in (
                ("development_oof", oof["outcome"], oof["probability"]),
                ("validation", validation["outcome"], validation_probability),
            ):
                rows.append({
                    "horizon_hours": int(horizon),
                    "lookback_hours": int(lookback),
                    "sample": sample,
                    **binary_metrics(outcome, probability),
                })
    return pd.DataFrame(rows)
