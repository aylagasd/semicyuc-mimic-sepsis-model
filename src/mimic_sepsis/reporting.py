"""Aggregate pre-test development/validation report construction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import pandas as pd

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
) -> DevelopmentReport:
    """Compare prevalence and clinical baseline without reading locked test."""
    columns = list(feature_columns)
    reference_oof, _ = grouped_prevalence_cross_validation(
        development, folds=folds, seed=seed
    )
    pipeline = make_logistic_pipeline(columns, c=logistic_c, seed=seed)
    candidate_oof, _ = grouped_cross_validation(
        development, pipeline, columns, folds=folds, seed=seed
    )
    keys = [
        "subject_id", "hadm_id", "stay_id", "landmark_time", "fold", "outcome"
    ]
    oof = reference_oof.rename(columns={"probability": "reference"}).merge(
        candidate_oof.rename(columns={"probability": "candidate"}),
        on=keys, validate="one_to_one",
    )
    oof = oof.merge(
        development[["subject_id", "hadm_id", "stay_id", "landmark_time", "event_time"]],
        on=["subject_id", "hadm_id", "stay_id", "landmark_time"],
        how="left", validate="one_to_one",
    )
    pipeline.fit(
        development[columns], development["outcome"],
        model__sample_weight=equal_patient_weights(development),
    )
    validation_predictions = validation[
        ["subject_id", "hadm_id", "stay_id", "landmark_time", "event_time", "outcome"]
    ].copy()
    validation_predictions["reference"] = patient_weighted_event_rate(development)
    validation_predictions["candidate"] = pipeline.predict_proba(
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
    for offset, (sample, frame) in enumerate(samples.items()):
        flow.append({
            "sample": sample,
            "landmarks": len(frame),
            "patients": frame["subject_id"].nunique(),
            "stays": frame["stay_id"].nunique(),
            "events": int(frame["outcome"].sum()),
            "prevalence": float(frame["outcome"].mean()),
        })
        for model in ("reference", "candidate"):
            metrics.append({
                "sample": sample, "model": model,
                **binary_metrics(frame["outcome"], frame[model]),
                **calibration_metrics(frame["outcome"], frame[model]),
            })
            estimates = patient_cluster_bootstrap_estimates(
                frame, frame[model], replicates=bootstrap_replicates,
                seed=seed + offset * 10 + (0 if model == "reference" else 1),
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
            if cohort is not None and subgroup_columns:
                audited = attach_audit_subgroups(frame, cohort)
                subgroup = subgroup_performance(
                    audited, audited[model], subgroup_columns=subgroup_columns,
                    minimum_events=subgroup_minimum_events,
                    minimum_nonevents=subgroup_minimum_nonevents,
                    privacy_minimum_cell=privacy_minimum_cell,
                )
                subgroup["sample"] = sample
                subgroup["model"] = model
                subgroups.append(subgroup)
        bootstrap = patient_cluster_bootstrap_comparison(
            frame, frame["reference"], frame["candidate"],
            replicates=bootstrap_replicates, seed=seed + offset,
        )
        summary = percentile_intervals(
            bootstrap, confidence_level=confidence_level
        )
        summary["sample"] = sample
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
    )
