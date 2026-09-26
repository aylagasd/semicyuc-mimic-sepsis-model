"""Partitioned temporal feature matrices from reduced MIMIC-IV Parquet."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from typing import Any

import duckdb

from .artifacts import ArtifactStore, ArtifactValidationError
from .chunked_landmarks import PARTITIONS, TARGETS, validate_partitions
from .chunked_sofa import (
    PartitionedDatasetManifest, _canonical_hash, validate_extract,
    validate_partitioned_dataset,
)
from .duckdb_runtime import configure_duckdb, validate_duckdb_runtime
from .feature_sources_sql import read_normalized_feature_events_sql
from .features import build_numeric_feature_matrix


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
        partitions: tuple[str, ...] = PARTITIONS,
        allow_non_demo_test: bool = False,
        duckdb_memory_limit: str = "8GB",
        duckdb_temp_dir: Path | None = None,
        duckdb_threads: int = 2,
    ) -> None:
        duckdb_memory_limit, duckdb_threads = validate_duckdb_runtime(
            duckdb_memory_limit, duckdb_threads
        )
        self.source_dir = Path(source_dir)
        self.landmark_run = Path(landmark_run)
        self.output_root = Path(output_root)
        self.feature_config_path = Path(feature_config_path)
        self.code_version = str(code_version)
        self.partitions = validate_partitions(partitions)
        self.allow_non_demo_test = bool(allow_non_demo_test)
        self.duckdb_memory_limit = duckdb_memory_limit
        self.duckdb_threads = duckdb_threads
        self.duckdb_temp_dir = Path(
            duckdb_temp_dir or self.output_root / "duckdb_tmp"
        )

    def run(self, *, resume: bool = False) -> dict[str, PartitionedDatasetManifest]:
        sources = validate_extract(self.source_dir)
        data_version = next(iter(sources.values())).data_version
        if (
            data_version != "2.2"
            and "test" in self.partitions
            and not self.allow_non_demo_test
        ):
            raise ArtifactValidationError(
                "Non-demo test materialization requires the gated full pipeline"
            )
        landmark_names = [
            f"{target}_{partition}_landmarks"
            for target in TARGETS for partition in self.partitions
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
            "backend": "duckdb-sql-pushdown-pandas-windows",
            "chunked_feature_schema_version": 4,
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
            "materialized_partitions": list(self.partitions),
            "duckdb_memory_limit": self.duckdb_memory_limit,
            "duckdb_threads": self.duckdb_threads,
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
        part_sequences = {
            tuple(str(part["name"]) for part in manifest.parts)
            for manifest in landmarks.values()
        }
        if len(part_sequences) != 1:
            raise ArtifactValidationError(
                "Landmark artifacts do not share the same ordered parts"
            )
        part_names = next(iter(part_sequences))
        connection = duckdb.connect()
        try:
            configure_duckdb(
                connection,
                memory_limit=self.duckdb_memory_limit,
                temp_directory=self.duckdb_temp_dir,
                threads=self.duckdb_threads,
            )
            for batch_index, part_name in enumerate(part_names):
                pending: list[tuple[str, str, dict[str, Any], Path]] = []
                for landmark_name in landmark_names:
                    feature_name = landmark_name.replace(
                        "_landmarks", "_features"
                    )
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
                    pending.append((
                        landmark_name, feature_name, part_config, landmark_path,
                    ))
                if not pending:
                    continue
                frames = {
                    landmark_name: connection.execute(
                        "SELECT * FROM read_parquet(?)", [str(landmark_path)]
                    ).fetchdf()
                    for landmark_name, _, _, landmark_path in pending
                }
                events = read_normalized_feature_events_sql(
                    connection,
                    landmark_path=[item[3] for item in pending],
                    cohort_path=self.source_dir / "cohort_stays.parquet",
                    chartevents_path=self.source_dir / "chartevents_reduced.parquet",
                    labevents_path=self.source_dir / "labevents_reduced.parquet",
                    maximum_lookback_hours=max(
                        int(value) for value in feature_config["lookbacks_hours"]
                    ),
                )
                for landmark_name, feature_name, part_config, _ in pending:
                    frame = frames[landmark_name]
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
