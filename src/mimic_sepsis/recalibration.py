"""Patient-weighted logistic recalibration for a frozen prediction model."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from collections.abc import Sequence

import numpy as np
import pandas as pd

from .modeling import equal_patient_weights


@dataclass(frozen=True)
class CalibrationReadiness:
    ready: bool
    patients: int | None
    event_patients: int | None
    nonevent_patients: int | None
    reason_codes: tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class LogisticRecalibrator:
    intercept: float
    slope: float
    epsilon: float
    fit_landmarks: int
    fit_patients: int

    def predict(self, probability: Sequence[float]) -> np.ndarray:
        """Apply the frozen intercept and slope to valid probabilities."""
        values = _probabilities(probability)
        logit = np.log(
            np.clip(values, self.epsilon, 1 - self.epsilon)
            / np.clip(1 - values, self.epsilon, 1)
        )
        linear = np.clip(self.intercept + self.slope * logit, -50, 50)
        return 1 / (1 + np.exp(-linear))


def _probabilities(probability: Sequence[float]) -> np.ndarray:
    values = np.asarray(probability, dtype=float)
    if values.ndim != 1 or len(values) == 0:
        raise ValueError("probability must be a non-empty one-dimensional sequence")
    if not np.isfinite(values).all() or ((values < 0) | (values > 1)).any():
        raise ValueError("probabilities must be finite and in [0, 1]")
    return values


def _patient_counts(table: pd.DataFrame) -> tuple[int, int, int]:
    missing = sorted({"subject_id", "outcome"} - set(table.columns))
    if missing:
        raise ValueError(f"table is missing columns: {', '.join(missing)}")
    if table.empty or table["subject_id"].isna().any():
        raise ValueError("table must contain non-missing patient identifiers")
    outcome = pd.to_numeric(table["outcome"], errors="raise")
    if not outcome.isin([0, 1]).all():
        raise ValueError("outcome must be binary")
    patient_event = table.assign(_outcome=outcome).groupby(
        "subject_id", sort=False
    )["_outcome"].max()
    event_patients = int(patient_event.sum())
    return len(patient_event), event_patients, int(len(patient_event) - event_patients)


def calibration_readiness(
    table: pd.DataFrame,
    *,
    minimum_event_patients: int,
    minimum_nonevent_patients: int,
    privacy_minimum_cell: int = 10,
) -> CalibrationReadiness:
    """Assess calibration information while suppressing small patient counts."""
    if minimum_event_patients <= 0 or minimum_nonevent_patients <= 0:
        raise ValueError("calibration patient minima must be positive")
    if privacy_minimum_cell <= 0:
        raise ValueError("privacy_minimum_cell must be positive")
    patients, event_patients, nonevent_patients = _patient_counts(table)
    reasons = []
    if event_patients < minimum_event_patients:
        reasons.append("insufficient_event_patients")
    if nonevent_patients < minimum_nonevent_patients:
        reasons.append("insufficient_nonevent_patients")

    def visible(value: int) -> int | None:
        return value if value == 0 or value >= privacy_minimum_cell else None

    return CalibrationReadiness(
        ready=not reasons,
        patients=visible(patients),
        event_patients=visible(event_patients),
        nonevent_patients=visible(nonevent_patients),
        reason_codes=tuple(reasons),
    )


def fit_logistic_recalibrator(
    table: pd.DataFrame,
    probability: Sequence[float],
    *,
    minimum_event_patients: int,
    minimum_nonevent_patients: int,
    epsilon: float = 1e-6,
    max_iter: int = 100,
    tolerance: float = 1e-8,
) -> LogisticRecalibrator:
    """Fit unpenalized logistic recalibration using equal patient influence."""
    readiness = calibration_readiness(
        table,
        minimum_event_patients=minimum_event_patients,
        minimum_nonevent_patients=minimum_nonevent_patients,
    )
    if not readiness.ready:
        raise ValueError(
            "Calibration sample lacks the prespecified patient information"
        )
    if not 0 < epsilon < 0.5 or max_iter <= 0 or tolerance <= 0:
        raise ValueError("epsilon, max_iter and tolerance are invalid")
    values = _probabilities(probability)
    if len(values) != len(table):
        raise ValueError("probability must align one-to-one with table")
    outcome = table["outcome"].to_numpy(dtype=float)
    logit = np.log(
        np.clip(values, epsilon, 1 - epsilon)
        / np.clip(1 - values, epsilon, 1)
    )
    design = np.column_stack([np.ones(len(table)), logit])
    patient_weight = equal_patient_weights(table)
    coefficient = np.array([0.0, 1.0])
    converged = False
    for _ in range(max_iter):
        linear = np.clip(design @ coefficient, -50, 50)
        fitted = 1 / (1 + np.exp(-linear))
        working_weight = patient_weight * np.clip(fitted * (1 - fitted), 1e-12, None)
        information = design.T @ (working_weight[:, None] * design)
        score = design.T @ (patient_weight * (outcome - fitted))
        try:
            step = np.linalg.solve(information, score)
        except np.linalg.LinAlgError as error:
            raise ValueError("Calibration information matrix is singular") from error
        coefficient += step
        if not np.isfinite(coefficient).all() or np.max(np.abs(coefficient)) > 50:
            raise ValueError("Calibration fit is unstable or separated")
        if np.max(np.abs(step)) < tolerance:
            converged = True
            break
    if not converged:
        raise ValueError("Calibration fit did not converge")
    return LogisticRecalibrator(
        intercept=float(coefficient[0]),
        slope=float(coefficient[1]),
        epsilon=float(epsilon),
        fit_landmarks=len(table),
        fit_patients=table["subject_id"].nunique(),
    )
