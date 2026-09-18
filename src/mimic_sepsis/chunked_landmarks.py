"""Partitioned leakage-safe landmark construction for full MIMIC-IV."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from .artifacts import ArtifactStore, ArtifactValidationError
from .chunked_sofa import (
    PartitionedDatasetManifest, _canonical_hash, validate_extract,
    validate_partitioned_dataset,
)
from .full_extract import _sql_path
from .landmarks import build_multiple_horizons
from .splits import patient_grouped_split


TARGETS = {
    "sepsis3": ("sepsis_stays", "t0"),
    "septic_shock": ("septic_shock_stays", "shock_t0"),
}
PARTITIONS = ("development", "validation", "test")


class ChunkedLandmarkBuilder:
    """Create risk sets per cohort batch and physical patient partition."""

    def __init__(
        self,
        source_dir: Path,
        sofa_run: Path,
        label_run: Path,
        output_root: Path,
        *,
        landmark_config_path: Path,
        split_config_path: Path,
        code_version: str = "unknown",
    ) -> None:
        self.source_dir = Path(source_dir)
        self.sofa_run = Path(sofa_run)
        self.label_run = Path(label_run)
        self.output_root = Path(output_root)
        self.landmark_config_path = Path(landmark_config_path)
        self.split_config_path = Path(split_config_path)
        self.code_version = str(code_version)

    def run(self, *, resume: bool = False) -> dict[str, PartitionedDatasetManifest]:
        sources = validate_extract(self.source_dir)
        sofa = validate_partitioned_dataset(self.sofa_run, "sofa_hourly")
        label_manifests = {
            artifact: validate_partitioned_dataset(
                self.label_run / artifact, artifact
            )
            for artifact, _ in TARGETS.values()
        }
        if len({item.config_sha256 for item in label_manifests.values()}) != 1:
            raise ArtifactValidationError("Label artifacts come from different runs")
        landmark_config = json.loads(
            self.landmark_config_path.read_text(encoding="utf-8")
        )
        split_config = json.loads(self.split_config_path.read_text(encoding="utf-8"))
        config: dict[str, Any] = {
            "backend": "partitioned-landmarks",
            "chunked_landmark_schema_version": 1,
            "code_version": self.code_version,
            "source_config_sha256": next(iter(sources.values())).config_sha256,
            "sofa_config_sha256": sofa.config_sha256,
            "label_config_sha256": next(iter(label_manifests.values())).config_sha256,
            "label_parts": {
                name: [
                    {key: part[key] for key in ("name", "rows", "sha256")}
                    for part in manifest.parts
                ]
                for name, manifest in label_manifests.items()
            },
            "landmarks": landmark_config,
            "splits": split_config,
        }
        config_hash = _canonical_hash(config)
        run_root = self.output_root / config_hash[:16]
        names = [
            f"{target}_{partition}_landmarks"
            for target in TARGETS for partition in PARTITIONS
        ]
        stores = {name: ArtifactStore(run_root / name / "parts") for name in names}
        collected: dict[str, list[dict[str, Any]]] = {name: [] for name in names}
        data_version = next(iter(sources.values())).data_version
        batch_size = int(sofa.metadata.get("batch_size", 0))
        if batch_size <= 0:
            raise ArtifactValidationError("SOFA manifest lacks a valid batch size")

        connection = duckdb.connect()
        cohort_path = _sql_path(self.source_dir / "cohort_stays.parquet")
        try:
            cohort = connection.execute(
                f"SELECT * FROM read_parquet('{cohort_path}') "
                "ORDER BY subject_id, intime, stay_id"
            ).fetchdf()
            if int(sofa.metadata.get("cohort_stays", -1)) != len(cohort):
                raise ArtifactValidationError("SOFA cohort cardinality does not match extract")
            patient_map = patient_grouped_split(
                cohort[["subject_id"]].drop_duplicates(),
                proportions=split_config["proportions"], seed=split_config["seed"],
            ).set_index("subject_id")["partition"]
            common = {
                "horizons_hours": tuple(landmark_config["horizons_hours"]),
                "minimum_observation_hours": landmark_config["minimum_observation_hours"],
                "landmark_interval_hours": landmark_config["landmark_interval_hours"],
            }
            for batch_index, sofa_part in enumerate(sofa.parts):
                part_name = str(sofa_part["name"])
                part_config = {**config, "batch_index": batch_index}
                valid = {}
                if resume:
                    for name, store in stores.items():
                        try:
                            valid[name] = store.validate(
                                part_name, expected_config=part_config
                            )
                        except (FileNotFoundError, ArtifactValidationError):
                            break
                    if len(valid) == len(names):
                        for name, manifest in valid.items():
                            collected[name].append({
                                "name": part_name, "rows": manifest.rows,
                                "sha256": manifest.sha256,
                            })
                        continue

                stays = cohort.iloc[
                    batch_index * batch_size:(batch_index + 1) * batch_size
                ].copy()
                for target, (label_artifact, event_column) in TARGETS.items():
                    label_path = (
                        self.label_run / label_artifact / "parts" /
                        f"{part_name}.parquet"
                    )
                    labels = connection.execute(
                        "SELECT * FROM read_parquet(?)", [str(label_path)]
                    ).fetchdf()
                    landmarks = build_multiple_horizons(
                        stays, labels, event_time_column=event_column, **common
                    )
                    landmarks["target"] = target
                    landmarks["partition"] = landmarks["subject_id"].map(
                        patient_map
                    ).astype("string")
                    for partition in PARTITIONS:
                        name = f"{target}_{partition}_landmarks"
                        frame = landmarks.loc[
                            landmarks["partition"].eq(partition)
                        ].reset_index(drop=True)
                        manifest = stores[name].write_dataframe(
                            part_name, frame, data_version=data_version,
                            code_version=self.code_version, config=part_config,
                        )
                        collected[name].append({
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
