"""Validated development/validation inputs for a full pre-test report."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
from pathlib import Path

import duckdb
import pandas as pd

from .artifacts import ArtifactValidationError
from .chunked_landmarks import TARGETS
from .chunked_sofa import (
    partitioned_dataset_columns,
    partitioned_dataset_sha256,
    read_partitioned_dataset,
    validate_extract,
    validate_partitioned_dataset,
)


@dataclass(frozen=True)
class PretestInputBundle:
    cohort: pd.DataFrame
    landmarks: Mapping[str, pd.DataFrame]
    features: Mapping[str, pd.DataFrame]
    data_version: str
    source_run_id: str
    source_artifacts: Mapping[str, str]
    target: str


def _read_cohort(path: Path) -> pd.DataFrame:
    connection = duckdb.connect()
    try:
        return connection.execute(
            "SELECT * FROM read_parquet(?)", [str(path)]
        ).fetchdf()
    finally:
        connection.close()


def load_partitioned_pretest_inputs(
    source_extract_dir: str | Path,
    landmark_run: str | Path,
    feature_run: str | Path,
    *,
    target: str = "sepsis3",
    feature_columns: Sequence[str] | None = None,
    horizon_hours: int | None = None,
) -> PretestInputBundle:
    """Load only development/validation after integrity and leakage checks."""
    if target not in TARGETS:
        raise ValueError(f"Unknown target: {target}")
    selected_features = None if feature_columns is None else list(feature_columns)
    if selected_features is not None and (
        not selected_features or len(selected_features) != len(set(selected_features))
    ):
        raise ValueError("feature_columns must be non-empty and unique")
    if horizon_hours is not None and horizon_hours <= 0:
        raise ValueError("horizon_hours must be positive")
    source_root = Path(source_extract_dir)
    landmark_root = Path(landmark_run)
    feature_root = Path(feature_run)
    sources = validate_extract(source_root)
    source_versions = {item.data_version for item in sources.values()}
    if len(source_versions) != 1:
        raise ArtifactValidationError("Extract data versions disagree")
    data_version = next(iter(source_versions))
    landmarks: dict[str, pd.DataFrame] = {}
    features: dict[str, pd.DataFrame] = {}
    source_artifacts = {"cohort_stays": sources["cohort_stays"].sha256}
    landmark_config_hashes: set[str] = set()
    feature_config_hashes: set[str] = set()
    for partition in ("development", "validation"):
        landmark_name = f"{target}_{partition}_landmarks"
        feature_name = f"{target}_{partition}_features"
        landmark_dir = landmark_root / landmark_name
        feature_dir = feature_root / feature_name
        landmark_manifest = validate_partitioned_dataset(
            landmark_dir, landmark_name
        )
        feature_manifest = validate_partitioned_dataset(feature_dir, feature_name)
        if (
            landmark_manifest.data_version != data_version
            or feature_manifest.data_version != data_version
        ):
            raise ArtifactValidationError("Pre-test input data versions disagree")
        if landmark_manifest.metadata.get("patient_partition") != partition:
            raise ArtifactValidationError("Landmark partition metadata mismatch")
        if feature_manifest.metadata.get("patient_partition") != partition:
            raise ArtifactValidationError("Feature partition metadata mismatch")
        landmark_config_hashes.add(landmark_manifest.config_sha256)
        feature_config_hashes.add(feature_manifest.config_sha256)
        source_artifacts[landmark_name] = partitioned_dataset_sha256(
            landmark_manifest
        )
        source_artifacts[feature_name] = partitioned_dataset_sha256(feature_manifest)
        feature_schema = set(partitioned_dataset_columns(
            feature_dir, feature_name, validated_manifest=feature_manifest
        ))
        forbidden = {"outcome", "event_time", "target", "partition"} & feature_schema
        if forbidden:
            raise ArtifactValidationError(
                "Feature input contains label/partition columns: "
                + ", ".join(sorted(forbidden))
            )
        landmark_columns = None
        landmark_filters = None
        if horizon_hours is not None:
            landmark_columns = [
                "subject_id", "hadm_id", "stay_id", "landmark_time",
                "horizon_hours", "horizon_observed", "outcome", "event_time",
            ]
            landmark_filters = {
                "horizon_hours": int(horizon_hours),
                "horizon_observed": True,
            }
        projected_features = None
        if selected_features is not None:
            projected_features = [
                "subject_id", "hadm_id", "stay_id", "landmark_time",
                *selected_features,
            ]
        landmarks[partition] = read_partitioned_dataset(
            landmark_dir, landmark_name, validated_manifest=landmark_manifest,
            columns=landmark_columns, filters=landmark_filters,
        )
        features[partition] = read_partitioned_dataset(
            feature_dir, feature_name, validated_manifest=feature_manifest,
            columns=projected_features,
        )
    if len(landmark_config_hashes) != 1 or len(feature_config_hashes) != 1:
        raise ArtifactValidationError("Development/validation inputs mix pipeline runs")
    development_ids = set(landmarks["development"]["subject_id"])
    validation_ids = set(landmarks["validation"]["subject_id"])
    if development_ids & validation_ids:
        raise ArtifactValidationError(
            "Patient leakage between development and validation landmarks"
        )
    if set(features["development"]["subject_id"]) & set(
        features["validation"]["subject_id"]
    ):
        raise ArtifactValidationError(
            "Patient leakage between development and validation features"
        )
    for partition in ("development", "validation"):
        landmark_ids = set(landmarks[partition]["subject_id"])
        feature_ids = set(features[partition]["subject_id"])
        if not landmark_ids.issubset(feature_ids):
            raise ArtifactValidationError(
                f"Landmark patients lack {partition} feature rows"
            )
    cohort = _read_cohort(source_root / "cohort_stays.parquet")
    modeled_ids = development_ids | validation_ids
    if not modeled_ids.issubset(set(cohort["subject_id"])):
        raise ArtifactValidationError("Modeled patients are absent from the cohort")
    return PretestInputBundle(
        cohort=cohort,
        landmarks=landmarks,
        features=features,
        data_version=data_version,
        source_run_id=(
            f"partitioned-{data_version}-{landmark_root.name}-{feature_root.name}"
        ),
        source_artifacts=source_artifacts,
        target=target,
    )


def load_partitioned_pretest_config(
    path: str | Path,
    *,
    feature_columns: Sequence[str] | None = None,
    horizon_hours: int | None = None,
) -> PretestInputBundle:
    """Load a local path-only input specification for notebook 13."""
    config_path = Path(path)
    try:
        value = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("Cannot read pre-test source config") from error
    if value.get("schema_version") != 1 or value.get("backend") != "partitioned":
        raise ValueError("Unsupported pre-test source configuration")
    required = ("source_extract_dir", "landmark_run", "feature_run")
    missing = [key for key in required if not str(value.get(key) or "").strip()]
    if missing:
        raise ValueError(
            "Pre-test source config is missing: " + ", ".join(missing)
        )

    def resolve(raw: str) -> Path:
        candidate = Path(raw)
        return candidate if candidate.is_absolute() else config_path.parent / candidate

    return load_partitioned_pretest_inputs(
        resolve(value["source_extract_dir"]),
        resolve(value["landmark_run"]),
        resolve(value["feature_run"]),
        target=str(value.get("target") or "sepsis3"),
        feature_columns=feature_columns,
        horizon_hours=horizon_hours,
    )
