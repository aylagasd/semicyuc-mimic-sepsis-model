"""Privacy-aware subgroup attachment and descriptive performance audits."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

from .evaluation import calibration_metrics
from .modeling import binary_metrics


AUDIT_COLUMNS = (
    "age_at_icu", "gender", "race", "admission_type", "admission_location",
    "insurance", "first_careunit",
)


def attach_audit_subgroups(table: pd.DataFrame, cohort: pd.DataFrame) -> pd.DataFrame:
    """Attach non-predictor audit descriptors to a landmark-level table."""
    required = {"stay_id"}
    for frame, name in ((table, "table"), (cohort, "cohort")):
        missing = sorted(required - set(frame.columns))
        if missing:
            raise ValueError(f"{name} is missing columns: {', '.join(missing)}")
    if cohort["stay_id"].duplicated().any():
        raise ValueError("cohort must be unique by stay_id")
    available = [column for column in AUDIT_COLUMNS if column in cohort]
    result = table.merge(
        cohort[["stay_id", *available]], on="stay_id", how="left",
        validate="many_to_one",
    )
    if "age_at_icu" in result:
        age = pd.to_numeric(result["age_at_icu"], errors="coerce")
        result["age_group"] = pd.cut(
            age, bins=[18, 45, 65, 80, np.inf], right=False,
            labels=["18-44", "45-64", "65-79", "80+"],
        ).astype("string").fillna("Missing")
    for column in available:
        if column != "age_at_icu":
            result[column] = result[column].astype("string").fillna("Missing")
    return result


def subgroup_performance(
    table: pd.DataFrame,
    probability: Sequence[float],
    *,
    subgroup_columns: Sequence[str],
    minimum_events: int = 20,
    minimum_nonevents: int = 20,
    privacy_minimum_cell: int = 10,
) -> pd.DataFrame:
    """Return descriptive subgroup metrics with small-cell suppression.

    Metrics are withheld unless both outcome classes meet the analytic minimum.
    Counts are also withheld when either class is below the privacy threshold,
    preventing recovery of a small cell by subtraction.
    """
    if minimum_events <= 0 or minimum_nonevents <= 0 or privacy_minimum_cell <= 0:
        raise ValueError("event and privacy minima must be positive")
    values = np.asarray(probability, dtype=float)
    if len(values) != len(table):
        raise ValueError("probabilities must align one-to-one with table")
    if not np.isfinite(values).all() or ((values < 0) | (values > 1)).any():
        raise ValueError("probabilities must be finite and in [0, 1]")
    required = {"subject_id", "outcome", *subgroup_columns}
    missing = sorted(required - set(table.columns))
    if missing:
        raise ValueError(f"table is missing columns: {', '.join(missing)}")
    source = table.copy()
    source["_probability"] = values
    rows = []
    metric_names = (
        "prevalence", "auroc", "auprc", "brier", "log_loss",
        "calibration_intercept", "calibration_slope",
    )
    for column in subgroup_columns:
        labels = source[column].astype("string").fillna("Missing")
        grouped = list(source.assign(_label=labels).groupby("_label", sort=True))
        counts = []
        for label, group in grouped:
            events = int(group["outcome"].sum())
            nonevents = int(len(group) - events)
            counts.append((str(label), group, events, nonevents))
        primary_suppressed = {
            label for label, _, events, nonevents in counts
            if events < privacy_minimum_cell or nonevents < privacy_minimum_cell
        }
        complementary_suppressed: set[str] = set()
        if primary_suppressed and len(counts) > len(primary_suppressed):
            candidates = [
                (events + nonevents, label)
                for label, _, events, nonevents in counts
                if label not in primary_suppressed
            ]
            complementary_suppressed.add(min(candidates)[1])
        for label, group, events, nonevents in counts:
            privacy_suppressed = (
                label in primary_suppressed or label in complementary_suppressed
            )
            privacy_safe = not privacy_suppressed
            reportable = (
                privacy_safe
                and events >= minimum_events and nonevents >= minimum_nonevents
                and group["subject_id"].nunique() >= 2
            )
            row = {
                "subgroup": column,
                "level": label,
                "privacy_suppressed": privacy_suppressed,
                "complementary_suppressed": label in complementary_suppressed,
                "metrics_reportable": reportable,
                "landmarks": len(group) if privacy_safe else pd.NA,
                "patients": group["subject_id"].nunique() if privacy_safe else pd.NA,
                "events": events if privacy_safe else pd.NA,
                "nonevents": nonevents if privacy_safe else pd.NA,
            }
            if reportable:
                row.update(binary_metrics(group["outcome"], group["_probability"]))
                row.update(calibration_metrics(group["outcome"], group["_probability"]))
            else:
                row.update({name: np.nan for name in metric_names})
            rows.append(row)
    result = pd.DataFrame(rows)
    for column in ("landmarks", "patients", "events", "nonevents"):
        result[column] = pd.array(result[column], dtype="Int64")
    return result
