"""Partitioned temporal feature matrices from reduced MIMIC-IV Parquet."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from .artifacts import ArtifactStore, ArtifactValidationError
from .chunked_landmarks import PARTITIONS, TARGETS
from .chunked_sofa import (
    PartitionedDatasetManifest, _canonical_hash, validate_extract,
    validate_partitioned_dataset,
)
from .feature_sources import normalize_lab_feature_events, normalize_vital_events
from .features import build_numeric_feature_matrix
from .full_extract import _sql_path


class ChunkedFeatureBuilder:
    """Build predictor-only matrices one landmark partition part at a time."""

    def __init__(
        self,
        source_dir: Path,
        landmark_run: Path,
        output_root: Path,
        *,
        feature_config_path: Path,
        code_version: str = "unknown",
    ) -> None:
        self.source_dir = Path(source_dir)
        self.landmark_run = Path(landmark_run)
        self.output_root = Path(output_root)
        self.feature_config_path = Path(feature_config_path)
        self.code_version = str(code_version)

    def run(self, *, resume: bool = False) -> dict[str, PartitionedDatasetManifest]:
        sources = validate_extract(self.source_dir)
        landmark_names = [
            f"{target}_{partition}_landmarks"
            for target in TARGETS for partition in PARTITIONS
        ]
        landmarks = {
            name: validate_partitioned_dataset(self.landmark_run / name, name)
            for name in landmark_names
        }
        if len({item.config_sha256 for item in landmarks.values()}) != 1:
            raise ArtifactValidationError("Landmark artifacts come from different runs")
        feature_config = json.loads(
            self.feature_config_path.read_text(encoding="utf-8")
        )
        config: dict[str, Any] = {
            "backend": "partitioned-features",
            "chunked_feature_schema_version": 1,
            "code_version": self.code_version,
            "source_config_sha256": next(iter(sources.values())).config_sha256,
            "landmark_config_sha256": next(iter(landmarks.values())).config_sha256,
            "landmark_parts": {
                name: [
                    {key: part[key] for key in ("name", "rows", "sha256")}
                    for part in manifest.parts
                ]
                for name, manifest in landmarks.items()
            },
            "features": feature_config,
        }
        config_hash = _canonical_hash(config)
        run_root = self.output_root / config_hash[:16]
        feature_names = [name.replace("_landmarks", "_features") for name in landmark_names]
        stores = {
            name: ArtifactStore(run_root / name / "parts") for name in feature_names
        }
        collected: dict[str, list[dict[str, Any]]] = {
            name: [] for name in feature_names
        }
        data_version = next(iter(sources.values())).data_version
        cohort_path = _sql_path(self.source_dir / "cohort_stays.parquet")
        chart_path = _sql_path(self.source_dir / "chartevents_reduced.parquet")
        lab_path = _sql_path(self.source_dir / "labevents_reduced.parquet")
        connection = duckdb.connect()
        try:
            for landmark_name, dataset in landmarks.items():
                feature_name = landmark_name.replace("_landmarks", "_features")
                for batch_index, item in enumerate(dataset.parts):
                    part_name = str(item["name"])
                    part_config = {
                        **config, "landmark_artifact": landmark_name,
                        "batch_index": batch_index,
                    }
                    if resume:
                        try:
                            manifest = stores[feature_name].validate(
                                part_name, expected_config=part_config
                            )
                            collected[feature_name].append({
                                "name": part_name, "rows": manifest.rows,
                                "sha256": manifest.sha256,
                            })
                            continue
                        except (FileNotFoundError, ArtifactValidationError):
                            pass
                    landmark_path = (
                        self.landmark_run / landmark_name / "parts" /
                        f"{part_name}.parquet"
                    )
                    frame = connection.execute(
                        "SELECT * FROM read_parquet(?)", [str(landmark_path)]
                    ).fetchdf()
                    keys = frame[["subject_id", "hadm_id", "stay_id"]].drop_duplicates()
                    connection.register("_keys", keys)
                    cohort = connection.execute(
                        f"SELECT cohort.* FROM read_parquet('{cohort_path}') cohort "
                        "JOIN _keys USING(subject_id,hadm_id,stay_id)"
                    ).fetchdf()
                    chart = connection.execute(
                        f"SELECT source.* FROM read_parquet('{chart_path}') source "
                        "JOIN (SELECT DISTINCT stay_id FROM _keys) keys USING(stay_id)"
                    ).fetchdf()
                    labs = connection.execute(
                        f"SELECT source.* FROM read_parquet('{lab_path}') source "
                        "JOIN (SELECT DISTINCT subject_id,hadm_id FROM _keys) keys "
                        "USING(subject_id,hadm_id)"
                    ).fetchdf()
                    events = pd.concat(
                        [normalize_vital_events(chart),
                         normalize_lab_feature_events(labs, cohort)],
                        ignore_index=True,
                    )
                    matrix = build_numeric_feature_matrix(
                        frame[["subject_id", "hadm_id", "stay_id", "landmark_time"]],
                        events,
                        variables=tuple(feature_config["variables"]),
                        lookbacks_hours=tuple(feature_config["lookbacks_hours"]),
                    )
                    manifest = stores[feature_name].write_dataframe(
                        part_name, matrix, data_version=data_version,
                        code_version=self.code_version, config=part_config,
                    )
                    collected[feature_name].append({
                        "name": part_name, "rows": manifest.rows,
                        "sha256": manifest.sha256,
                    })
        finally:
            connection.close()

        outputs = {}
        for name, parts in collected.items():
            manifest = PartitionedDatasetManifest(
                artifact=name, data_version=data_version,
                config_sha256=config_hash,
                rows=sum(int(part["rows"]) for part in parts),
                parts=tuple(parts),
                metadata={"patient_partition": name.split("_")[-2]},
            )
            directory = run_root / name
            directory.mkdir(parents=True, exist_ok=True)
            temporary = directory / f"{name}.partial.json"
            temporary.write_text(
                json.dumps(asdict(manifest), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            temporary.replace(directory / f"{name}.dataset.json")
            outputs[name] = manifest
        return outputs
