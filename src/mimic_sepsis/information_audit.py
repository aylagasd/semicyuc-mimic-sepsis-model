"""Aggregate information audit before formal prediction-model sample sizing."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

import duckdb


IDENTIFIER_COLUMNS = {"subject_id", "hadm_id", "stay_id", "landmark_time"}


@dataclass(frozen=True)
class DevelopmentInformation:
    target: str
    horizon_hours: int
    observed_landmarks: int
    positive_landmarks: int
    negative_landmarks: int
    censored_landmarks: int
    patients: int
    patients_with_event: int
    stays: int
    baseline_parameters: int
    available_engineered_predictors: int
    formal_sample_size_ready: bool

    def to_dict(self) -> dict:
        return asdict(self)


def audit_development_information(
    landmark_path: str | Path,
    feature_path: str | Path,
    *,
    target: str,
    horizon_hours: int,
    baseline_features: Sequence[str],
    anticipated_cox_snell_r2: float | None,
) -> DevelopmentInformation:
    """Return only aggregate counts and fail if non-development rows are present."""
    connection = duckdb.connect()
    try:
        landmark_path, feature_path = str(landmark_path), str(feature_path)
        partitions = connection.execute(
            "SELECT DISTINCT partition FROM read_parquet(?)", [landmark_path]
        ).fetchall()
        if partitions != [("development",)]:
            raise ValueError("Information planning accepts development landmarks only")
        row = connection.execute(
            """
            SELECT
              count(*) FILTER (WHERE outcome IS NOT NULL),
              count(*) FILTER (WHERE outcome=1),
              count(*) FILTER (WHERE outcome=0),
              count(*) FILTER (WHERE outcome IS NULL),
              count(DISTINCT subject_id),
              count(DISTINCT subject_id) FILTER (WHERE outcome=1),
              count(DISTINCT stay_id)
            FROM read_parquet(?)
            WHERE target=? AND horizon_hours=?
            """,
            [landmark_path, target, int(horizon_hours)],
        ).fetchone()
        schema = connection.execute(
            "DESCRIBE SELECT * FROM read_parquet(?)", [feature_path]
        ).fetchall()
        predictors = [item[0] for item in schema if item[0] not in IDENTIFIER_COLUMNS]
        missing = sorted(set(baseline_features) - set(predictors))
        if missing:
            raise ValueError(f"Baseline features absent from matrix: {', '.join(missing)}")
        return DevelopmentInformation(
            target=target,
            horizon_hours=int(horizon_hours),
            observed_landmarks=int(row[0]),
            positive_landmarks=int(row[1]),
            negative_landmarks=int(row[2]),
            censored_landmarks=int(row[3]),
            patients=int(row[4]),
            patients_with_event=int(row[5]),
            stays=int(row[6]),
            baseline_parameters=len(tuple(baseline_features)),
            available_engineered_predictors=len(predictors),
            formal_sample_size_ready=anticipated_cox_snell_r2 is not None,
        )
    finally:
        connection.close()

