import numpy as np
import pandas as pd

from mimic_sepsis.reporting import build_development_report
from mimic_sepsis.modeling import make_gradient_boosting_pipeline


def _table(start, patients=20):
    rows = []
    for subject in range(start, start + patients):
        for hour in (6, 7):
            rows.append({
                "subject_id": subject, "hadm_id": subject + 100,
                "stay_id": subject + 200,
                "landmark_time": pd.Timestamp(year=2100, month=1, day=1, hour=hour),
                "outcome": int(subject % 2 == 0 and hour == 7),
                "event_time": (
                    pd.Timestamp(year=2100, month=1, day=1, hour=8)
                    if subject % 2 == 0 else pd.NaT
                ),
                "heart_rate_last_24h": 70 + subject % 7,
                "map_min_24h": 55 + subject % 11,
            })
    return pd.DataFrame(rows)


def test_report_is_aggregate_and_uses_both_samples():
    cohort = pd.concat([_table(1), _table(101)], ignore_index=True)[
        ["stay_id", "subject_id"]
    ].drop_duplicates("stay_id")
    cohort["age_at_icu"] = 50
    cohort["gender"] = np.where(cohort["subject_id"] % 2, "F", "M")
    report = build_development_report(
        _table(1), _table(101),
        feature_columns=("heart_rate_last_24h", "map_min_24h"),
        folds=2, logistic_c=1.0, bootstrap_replicates=10,
        confidence_level=0.8, seed=42, exploratory_thresholds=(0.1, 0.2),
        cohort=cohort, subgroup_columns=("age_group", "gender"),
        subgroup_minimum_events=2, subgroup_minimum_nonevents=2,
        privacy_minimum_cell=2,
        nonlinear_pipeline=make_gradient_boosting_pipeline(
            ("heart_rate_last_24h", "map_min_24h"),
            max_iter=10, max_leaf_nodes=3, min_samples_leaf=2, seed=42,
        ),
    )
    assert set(report.sample_flow["sample"]) == {"development_oof", "validation"}
    assert len(report.point_metrics) == 6
    assert len(report.paired_intervals) == 24
    assert len(report.metric_intervals) == 6 * 10
    assert len(report.threshold_metrics) == 12
    assert {"alerts_per_100_patient_days", "median_warning_hours"} <= set(
        report.threshold_metrics
    )
    assert set(report.decision_curves["strategy"]) == {
        "reference", "logistic", "gradient_boosting", "treat_all", "treat_none"
    }
    assert set(report.paired_intervals["comparison"]) == {
        "logistic_minus_reference", "gradient_boosting_minus_reference",
        "gradient_boosting_minus_logistic",
    }
    assert set(report.subgroup_performance["subgroup"]) == {
        "age_group", "gender", "missingness_group",
    }
    assert set(report.missingness_summary["feature"]) == {
        "heart_rate_last_24h", "map_min_24h",
    }
    assert set(report.missingness_summary["sample"]) == {
        "development_oof", "validation",
    }
    assert report.paired_intervals["successful_replicates"].between(0, 10).all()
    assert not any(
        column in report.point_metrics for column in ("subject_id", "stay_id")
    )
    assert np.isfinite(report.point_metrics["brier"]).all()
