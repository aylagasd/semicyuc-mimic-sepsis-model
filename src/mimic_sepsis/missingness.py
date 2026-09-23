"""Privacy-aware audits of predictor availability and missingness burden."""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd


def _require(frame: pd.DataFrame, columns: set[str], name: str) -> None:
    missing = sorted(columns - set(frame.columns))
    if missing:
        raise ValueError(f"{name} is missing columns: {', '.join(missing)}")


def feature_missingness_summary(
    table: pd.DataFrame,
    feature_columns: Sequence[str],
    *,
    privacy_minimum_cell: int = 10,
) -> pd.DataFrame:
    """Summarize feature availability without exposing small positive cells.

    A complete feature row is withheld when any landmark- or patient-level
    observed/missing cell is positive but below the privacy threshold. Zeros
    remain reportable because they do not identify a rare observed person.
    """
    columns = list(feature_columns)
    if not columns or len(columns) != len(set(columns)):
        raise ValueError("feature_columns must be non-empty and unique")
    if privacy_minimum_cell <= 0:
        raise ValueError("privacy_minimum_cell must be positive")
    _require(table, {"subject_id", "stay_id", *columns}, "table")
    rows = []
    for feature in columns:
        missing = table[feature].isna()
        observed = ~missing
        counts = {
            "landmarks": len(table),
            "patients": table["subject_id"].nunique(),
            "stays": table["stay_id"].nunique(),
            "missing_landmarks": int(missing.sum()),
            "observed_landmarks": int(observed.sum()),
            "patients_with_missing": table.loc[missing, "subject_id"].nunique(),
            "patients_with_observed": table.loc[observed, "subject_id"].nunique(),
        }
        protected_cells = (
            counts["missing_landmarks"], counts["observed_landmarks"],
            counts["patients_with_missing"], counts["patients_with_observed"],
        )
        suppressed = any(
            0 < value < privacy_minimum_cell for value in protected_cells
        )
        row: dict[str, object] = {
            "feature": feature,
            "privacy_suppressed": suppressed,
        }
        if suppressed:
            row.update({key: pd.NA for key in counts})
            row["missing_fraction"] = float("nan")
        else:
            row.update(counts)
            row["missing_fraction"] = float(missing.mean())
        rows.append(row)
    result = pd.DataFrame(rows)
    for column in (
        "landmarks", "patients", "stays", "missing_landmarks",
        "observed_landmarks", "patients_with_missing", "patients_with_observed",
    ):
        result[column] = pd.array(result[column], dtype="Int64")
    return result


def attach_missingness_burden(
    table: pd.DataFrame,
    feature_columns: Sequence[str],
) -> pd.DataFrame:
    """Attach row-level missing-feature counts for local audit, not prediction."""
    columns = list(feature_columns)
    if not columns or len(columns) != len(set(columns)):
        raise ValueError("feature_columns must be non-empty and unique")
    _require(table, set(columns), "table")
    result = table.copy()
    count = result[columns].isna().sum(axis=1).astype("int16")
    result["missing_features"] = count
    result["missing_fraction"] = count / len(columns)
    result["missingness_group"] = pd.cut(
        count,
        bins=[-1, 0, 1, float("inf")],
        labels=["0 missing", "1 missing", "2+ missing"],
    ).astype("string")
    return result
