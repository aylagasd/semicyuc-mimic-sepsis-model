"""Reproducible patient-grouped dataset partitioning."""

from __future__ import annotations

import numpy as np
import pandas as pd


SPLIT_ORDER = ("development", "validation", "test")


def patient_grouped_split(
    frame: pd.DataFrame,
    *,
    subject_column: str = "subject_id",
    proportions: dict[str, float] | None = None,
    seed: int = 20260909,
) -> pd.DataFrame:
    """Assign every row of a patient to one deterministic partition.

    Allocation targets exact patient counts using largest remainders. It does
    not inspect outcomes, preventing label-guided manipulation of the test set.
    """
    if subject_column not in frame:
        raise ValueError(f"frame is missing column: {subject_column}")
    if frame[subject_column].isna().any():
        raise ValueError("subject identifiers cannot be missing")
    proportions = proportions or {
        "development": 0.70, "validation": 0.15, "test": 0.15
    }
    if set(proportions) != set(SPLIT_ORDER):
        raise ValueError(f"proportions must define: {', '.join(SPLIT_ORDER)}")
    if any(value <= 0 for value in proportions.values()) or not np.isclose(
        sum(proportions.values()), 1.0
    ):
        raise ValueError("split proportions must be positive and sum to one")

    subjects = np.array(sorted(frame[subject_column].unique(), key=str), dtype=object)
    rng = np.random.default_rng(seed)
    subjects = subjects[rng.permutation(len(subjects))]
    exact = np.array([proportions[name] * len(subjects) for name in SPLIT_ORDER])
    counts = np.floor(exact).astype(int)
    remainder_order = np.argsort(-(exact - counts), kind="stable")
    for index in remainder_order[: len(subjects) - counts.sum()]:
        counts[index] += 1
    mapping = {}
    start = 0
    for name, count in zip(SPLIT_ORDER, counts, strict=True):
        mapping.update({subject: name for subject in subjects[start : start + count]})
        start += count
    result = frame.copy()
    result["partition"] = result[subject_column].map(mapping).astype("string")
    assert_patient_isolation(result, subject_column=subject_column)
    return result


def assert_patient_isolation(
    frame: pd.DataFrame, *, subject_column: str = "subject_id"
) -> None:
    """Raise if a patient occurs in more than one partition."""
    required = {subject_column, "partition"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"frame is missing columns: {', '.join(sorted(missing))}")
    counts = frame.groupby(subject_column, dropna=False)["partition"].nunique()
    if counts.gt(1).any():
        raise ValueError("At least one patient occurs in multiple partitions")
