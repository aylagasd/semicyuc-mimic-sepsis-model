"""Aggregate pre-test development/validation report construction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import pandas as pd
from sklearn.base import clone
from sklearn.pipeline import Pipeline

from .evaluation import (
    calibration_metrics, decision_curve, patient_cluster_bootstrap_comparison,
    operational_alert_metrics, patient_cluster_bootstrap_estimates,
    percentile_intervals, threshold_metrics,
)
from .modeling import (
    binary_metrics, equal_patient_weights, grouped_cross_validation,
    grouped_prevalence_cross_validation, make_logistic_pipeline,
    patient_weighted_event_rate,
)
from .missingness import attach_missingness_burden, feature_missingness_summary
from .subgroups import attach_audit_subgroups, subgroup_performance


@dataclass(frozen=True)
class DevelopmentReport:
    sample_flow: pd.DataFrame
    point_metrics: pd.DataFrame
    paired_intervals: pd.DataFrame
    metric_intervals: pd.DataFrame
    threshold_metrics: pd.DataFrame
    decision_curves: pd.DataFrame
    subgroup_performance: pd.DataFrame
    missingness_summary: pd.DataFrame


def build_development_report(
    development: pd.DataFrame,
    validation: pd.DataFrame,
    *,
    feature_columns: Sequence[str],
    folds: int,
    logistic_c: float,
    bootstrap_replicates: int,
    confidence_level: float,
    seed: int,
    exploratory_thresholds: Sequence[float] = (),
    cohort: pd.DataFrame | None = None,
    subgroup_columns: Sequence[str] = (),
    subgroup_minimum_events: int = 20,
    subgroup_minimum_nonevents: int = 20,
    privacy_minimum_cell: int = 10,
    nonlinear_pipeline: Pipeline | None = None,
) -> DevelopmentReport:
    """Compare prespecified models without reading the locked test."""
    columns = list(feature_columns)
    reference_oof, _ = grouped_prevalence_cross_validation(
        development, folds=folds, seed=seed
    )
    pipeline = make_logistic_pipeline(columns, c=logistic_c, seed=seed)
    logistic_oof, _ = grouped_cross_validation(
        development, pipeline, columns, folds=folds, seed=seed
    )
    keys = [
        "subject_id", "hadm_id", "stay_id", "landmark_time", "fold", "outcome"
    ]
    oof = reference_oof.rename(columns={"probability": "reference"}).merge(
        logistic_oof.rename(columns={"probability": "logistic"}),
        on=keys, validate="one_to_one",
    )
    oof = oof.merge(
        development[[
            "subject_id", "hadm_id", "stay_id", "landmark_time", "event_time",
            *columns,
        ]],
        on=["subject_id", "hadm_id", "stay_id", "landmark_time"],
        how="left", validate="one_to_one",
    )
    model_names = ["reference", "logistic"]
    if nonlinear_pipeline is not None:
        nonlinear_oof, _ = grouped_cross_validation(
            development, nonlinear_pipeline, columns, folds=folds, seed=seed
        )
        oof = oof.merge(
            nonlinear_oof[keys + ["probability"]].rename(
                columns={"probability": "gradient_boosting"}
            ),
            on=keys, validate="one_to_one",
        )
        model_names.append("gradient_boosting")
    pipeline.fit(
        development[columns], development["outcome"],
        model__sample_weight=equal_patient_weights(development),
    )
    validation_predictions = validation[
        [
            "subject_id", "hadm_id", "stay_id", "landmark_time", "event_time",
            "outcome", *columns,
        ]
    ].copy()
    validation_predictions["reference"] = patient_weighted_event_rate(development)
    validation_predictions["logistic"] = pipeline.predict_proba(
        validation[columns]
    )[:, 1]
    if nonlinear_pipeline is not None:
        fitted_nonlinear = clone(nonlinear_pipeline)
        fitted_nonlinear.fit(
            development[columns], development["outcome"],
            model__sample_weight=equal_patient_weights(development),
        )
        validation_predictions["gradient_boosting"] = fitted_nonlinear.predict_proba(
            validation[columns]
        )[:, 1]
    samples = {
        "development_oof": oof,
        "validation": validation_predictions,
    }
    flow = []
    metrics = []
    intervals = []
    metric_intervals = []
    operating = []
    curves = []
    subgroups = []
    missingness_summaries = []
    for offset, (sample, frame) in enumerate(samples.items()):
        flow.append({
            "sample": sample,
            "landmarks": len(frame),
            "patients": frame["subject_id"].nunique(),
            "stays": frame["stay_id"].nunique(),
            "events": int(frame["outcome"].sum()),
            "prevalence": float(frame["outcome"].mean()),
        })
        availability = feature_missingness_summary(
            frame, columns, privacy_minimum_cell=privacy_minimum_cell
        )
        availability["sample"] = sample
        missingness_summaries.append(availability)
        audited = attach_missingness_burden(frame, columns)
        audit_columns = ["missingness_group"]
        if cohort is not None and subgroup_columns:
            audited = attach_audit_subgroups(audited, cohort)
            audit_columns = [*subgroup_columns, *audit_columns]
        for model_index, model in enumerate(model_names):
            metrics.append({
                "sample": sample, "model": model,
                **binary_metrics(frame["outcome"], frame[model]),
                **calibration_metrics(frame["outcome"], frame[model]),
            })
            estimates = patient_cluster_bootstrap_estimates(
                frame, frame[model], replicates=bootstrap_replicates,
                seed=seed + offset * 10 + model_index,
            )
            estimate_summary = percentile_intervals(
                estimates, confidence_level=confidence_level
            )
            estimate_summary["sample"] = sample
            estimate_summary["model"] = model
            metric_intervals.append(estimate_summary)
            for threshold in exploratory_thresholds:
                operating.append({
                    "sample": sample, "model": model,
                    **threshold_metrics(
                        frame["outcome"], frame[model], threshold=float(threshold)
                    ),
                    **operational_alert_metrics(
                        frame, frame[model], threshold=float(threshold)
                    ),
                })
            curve = decision_curve(
                frame["outcome"], frame[model], thresholds=exploratory_thresholds
            ) if exploratory_thresholds else pd.DataFrame()
            if not curve.empty:
                curve = curve.loc[
                    curve["strategy"].eq("model")
                    | ((model == "reference") & ~curve["strategy"].eq("model"))
                ].copy()
                curve.loc[curve["strategy"].eq("model"), "strategy"] = model
                curve["sample"] = sample
                curves.append(curve)
            subgroup = subgroup_performance(
                audited, audited[model], subgroup_columns=audit_columns,
                minimum_events=subgroup_minimum_events,
                minimum_nonevents=subgroup_minimum_nonevents,
                privacy_minimum_cell=privacy_minimum_cell,
            )
            subgroup["sample"] = sample
            subgroup["model"] = model
            subgroups.append(subgroup)
        comparisons = [("logistic_minus_reference", "reference", "logistic")]
        if nonlinear_pipeline is not None:
            comparisons.extend([
                ("gradient_boosting_minus_reference", "reference", "gradient_boosting"),
                ("gradient_boosting_minus_logistic", "logistic", "gradient_boosting"),
            ])
        for comparison_index, (name, reference, candidate) in enumerate(comparisons):
            bootstrap = patient_cluster_bootstrap_comparison(
                frame, frame[reference], frame[candidate],
                replicates=bootstrap_replicates,
                seed=seed + offset * 10 + 100 + comparison_index,
            )
            summary = percentile_intervals(
                bootstrap, confidence_level=confidence_level
            )
            summary["sample"] = sample
            summary["comparison"] = name
            intervals.append(summary)
    return DevelopmentReport(
        sample_flow=pd.DataFrame(flow),
        point_metrics=pd.DataFrame(metrics),
        paired_intervals=pd.concat(intervals, ignore_index=True),
        metric_intervals=pd.concat(metric_intervals, ignore_index=True),
        threshold_metrics=pd.DataFrame(operating),
        decision_curves=pd.concat(curves, ignore_index=True) if curves else pd.DataFrame(
            columns=["threshold", "strategy", "net_benefit", "sample"]
        ),
        subgroup_performance=(
            pd.concat(subgroups, ignore_index=True) if subgroups else pd.DataFrame()
        ),
        missingness_summary=pd.concat(missingness_summaries, ignore_index=True),
    )
