"""Bounded-memory Sepsis-3 and septic-shock labels over partitioned SOFA."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from .antimicrobials import (
    classify_prescriptions, confirm_administrations, load_antimicrobial_rules,
)
from .artifacts import ArtifactStore, ArtifactValidationError
from .chunked_sofa import (
    PartitionedDatasetManifest, _canonical_hash, validate_extract,
    validate_partitioned_dataset,
)
from .duckdb_runtime import configure_duckdb, validate_duckdb_runtime
from .full_extract import _sql_path
from .infection import pair_antibiotics_and_cultures
from .sepsis_labels import (
    build_sepsis_episodes, first_sepsis_episode_per_stay,
    sepsis_episode_parameters,
)
from .septic_shock import (
    build_septic_shock_labels, normalize_lactate, normalize_vasopressor_intervals,
)


PRIMARY_LABEL_ARTIFACTS = (
    "suspected_infection_pairs",
    "sepsis_episodes",
    "sepsis_stays",
    "septic_shock_stays",
)
COMPLETE_SOFA_ARTIFACTS = (
    "sepsis_episodes_complete_sofa",
    "sepsis_stays_complete_sofa",
)
LABEL_ARTIFACTS = (
    "suspected_infection_pairs",
    "sepsis_episodes",
    "sepsis_stays",
    *COMPLETE_SOFA_ARTIFACTS,
    "septic_shock_stays",
)


class ChunkedLabelBuilder:
    """Build labels per SOFA partition while preserving admission boundaries."""

    def __init__(
        self,
        source_dir: Path,
        sofa_run: Path,
        output_root: Path,
        *,
        rules_path: Path,
        sepsis_config_path: Path,
        shock_config_path: Path,
        code_version: str = "unknown",
        duckdb_memory_limit: str = "8GB",
        duckdb_temp_dir: Path | None = None,
        duckdb_threads: int = 2,
    ) -> None:
        self.source_dir = Path(source_dir)
        self.sofa_run = Path(sofa_run)
        self.output_root = Path(output_root)
        self.rules_path = Path(rules_path)
        self.sepsis_config_path = Path(sepsis_config_path)
        self.shock_config_path = Path(shock_config_path)
        self.code_version = str(code_version)
        self.duckdb_memory_limit, self.duckdb_threads = validate_duckdb_runtime(
            duckdb_memory_limit, duckdb_threads
        )
        self.duckdb_temp_dir = Path(
            duckdb_temp_dir or self.output_root / "duckdb_tmp"
        )

    def _configuration(
        self, source_sha: dict[str, str], sofa: PartitionedDatasetManifest
    ) -> dict[str, Any]:
        return {
            "backend": "partitioned-pandas-labels",
            "chunked_label_schema_version": 4,
            "code_version": self.code_version,
            "duckdb_memory_limit": self.duckdb_memory_limit,
            "duckdb_threads": self.duckdb_threads,
            "source_sha256": source_sha,
            "sofa_config_sha256": sofa.config_sha256,
            "sofa_parts": [
                {key: part[key] for key in ("name", "rows", "sha256")}
                for part in sofa.parts
            ],
            "antimicrobial_rules_sha256": hashlib.sha256(
                self.rules_path.read_bytes()
            ).hexdigest(),
            "sepsis3": json.loads(
                self.sepsis_config_path.read_text(encoding="utf-8")
            ),
            "shock_config": json.loads(
                self.shock_config_path.read_text(encoding="utf-8")
            ),
        }

    def _read_for_batch(
        self, connection: duckdb.DuckDBPyConnection, artifact: str, join: str
    ) -> pd.DataFrame:
        path = _sql_path(self.source_dir / f"{artifact}.parquet")
        return connection.execute(
            f"SELECT source.* FROM read_parquet('{path}') source "
            f"JOIN _batch {join}"
        ).fetchdf()

    def run(self, *, resume: bool = False) -> dict[str, PartitionedDatasetManifest]:
        sources = validate_extract(self.source_dir)
        sofa_manifest = validate_partitioned_dataset(self.sofa_run, "sofa_hourly")
        config = self._configuration(
            {name: item.sha256 for name, item in sources.items()}, sofa_manifest
        )
        config_hash = _canonical_hash(config)
        run_root = self.output_root / config_hash[:16]
        data_version = next(iter(sources.values())).data_version
        stores = {
            artifact: ArtifactStore(run_root / artifact / "parts")
            for artifact in LABEL_ARTIFACTS
        }
        collected: dict[str, list[dict[str, Any]]] = {
            artifact: [] for artifact in LABEL_ARTIFACTS
        }
        rules = load_antimicrobial_rules(self.rules_path)
        shock_config = config["shock_config"]
        cohort_path = _sql_path(self.source_dir / "cohort_stays.parquet")
        connection = duckdb.connect()
        try:
            configure_duckdb(
                connection,
                memory_limit=self.duckdb_memory_limit,
                temp_directory=self.duckdb_temp_dir,
                threads=self.duckdb_threads,
            )
            batch_size = int(sofa_manifest.metadata.get("batch_size", 0))
            if batch_size <= 0:
                raise ArtifactValidationError("SOFA manifest lacks a valid batch size")
            ordered_stays = connection.execute(
                f"SELECT stay_id FROM read_parquet('{cohort_path}') "
                "ORDER BY subject_id, intime, stay_id"
            ).fetchall()
            if int(sofa_manifest.metadata.get("cohort_stays", -1)) != len(ordered_stays):
                raise ArtifactValidationError("SOFA cohort cardinality does not match extract")
            for batch_index, sofa_part in enumerate(sofa_manifest.parts):
                part_name = str(sofa_part["name"])
                part_config = {**config, "batch_index": batch_index}
                if resume:
                    valid = {}
                    for artifact, store in stores.items():
                        try:
                            valid[artifact] = store.validate(
                                part_name, expected_config=part_config
                            )
                        except (FileNotFoundError, ArtifactValidationError):
                            break
                    if len(valid) == len(LABEL_ARTIFACTS):
                        for artifact, manifest in valid.items():
                            collected[artifact].append({
                                "name": part_name, "rows": manifest.rows,
                                "sha256": manifest.sha256,
                            })
                        continue

                sofa_path = self.sofa_run / "parts" / f"{part_name}.parquet"
                sofa = connection.execute(
                    "SELECT * FROM read_parquet(?)", [str(sofa_path)]
                ).fetchdf()
                batch_ids = pd.DataFrame({
                    "stay_id": [
                        int(row[0]) for row in ordered_stays[
                            batch_index * batch_size:(batch_index + 1) * batch_size
                        ]
                    ]
                })
                connection.register("_batch_ids", batch_ids)
                cohort = connection.execute(
                    f"SELECT cohort.* FROM read_parquet('{cohort_path}') cohort "
                    "JOIN _batch_ids USING(stay_id)"
                ).fetchdf()
                connection.register(
                    "_batch", cohort[["subject_id", "hadm_id", "stay_id"]]
                )

                prescriptions = self._read_for_batch(
                    connection, "prescriptions_cohort", "USING(subject_id,hadm_id)"
                )
                emar = self._read_for_batch(
                    connection, "emar_cohort", "USING(subject_id,hadm_id)"
                )
                microbiology = self._read_for_batch(
                    connection, "microbiology_cohort", "USING(subject_id,hadm_id)"
                )
                classified = classify_prescriptions(prescriptions, rules)
                confirmed = confirm_administrations(classified, emar)
                antibiotics = confirmed.dropna(subset=["administration_time"])[
                    ["subject_id", "hadm_id", "pharmacy_id", "administration_time"]
                ].rename(columns={
                    "pharmacy_id": "antibiotic_id",
                    "administration_time": "antibiotic_time",
                })
                microbiology["culture_time"] = pd.to_datetime(
                    microbiology["charttime"], errors="coerce"
                ).fillna(pd.to_datetime(microbiology["chartdate"], errors="coerce"))
                cultures = (
                    microbiology.loc[
                        microbiology["spec_type_desc"].fillna("").str.contains(
                            "BLOOD", case=False
                        )
                    ]
                    .dropna(subset=[
                        "subject_id", "hadm_id", "micro_specimen_id", "culture_time"
                    ])
                    .sort_values("culture_time")
                    .drop_duplicates(["subject_id", "hadm_id", "micro_specimen_id"])
                    [["subject_id", "hadm_id", "micro_specimen_id", "culture_time"]]
                    .rename(columns={"micro_specimen_id": "culture_id"})
                )
                pairs = pair_antibiotics_and_cultures(antibiotics, cultures)
                for column in ("antibiotic_time", "culture_time", "t_si"):
                    pairs[column] = pairs[column].astype("datetime64[ns]")
                sepsis_config = config["sepsis3"]
                episodes = build_sepsis_episodes(
                    pairs, cohort, sofa,
                    **sepsis_episode_parameters(sepsis_config),
                )
                sepsis_stays = first_sepsis_episode_per_stay(episodes)
                complete_episodes = build_sepsis_episodes(
                    pairs, cohort, sofa,
                    **sepsis_episode_parameters(
                        sepsis_config, sensitivity="complete_components"
                    ),
                )
                complete_stays = first_sepsis_episode_per_stay(
                    complete_episodes
                )
                lactates = normalize_lactate(self._read_for_batch(
                    connection, "labevents_reduced", "USING(subject_id,hadm_id)"
                ))
                vasopressors = normalize_vasopressor_intervals(self._read_for_batch(
                    connection, "inputevents_reduced", "USING(stay_id)"
                ))
                shock = build_septic_shock_labels(
                    sepsis_stays,
                    lactates,
                    vasopressors,
                    lactate_threshold=shock_config["lactate_threshold_mmol_l"],
                    concurrency_hours=shock_config["concurrency_hours"],
                    association_hours=shock_config["sepsis_association_hours_after"],
                )
                frames = dict(zip(
                    LABEL_ARTIFACTS,
                    (
                        pairs, episodes, sepsis_stays, complete_episodes,
                        complete_stays, shock,
                    ),
                    strict=True,
                ))
                for artifact, frame in frames.items():
                    manifest = stores[artifact].write_dataframe(
                        part_name, frame, data_version=data_version,
                        code_version=self.code_version, config=part_config,
                    )
                    collected[artifact].append({
                        "name": part_name, "rows": manifest.rows,
                        "sha256": manifest.sha256,
                    })
        finally:
            connection.close()

        outputs = {}
        for artifact, parts in collected.items():
            manifest = PartitionedDatasetManifest(
                artifact=artifact,
                data_version=data_version,
                config_sha256=config_hash,
                rows=sum(int(part["rows"]) for part in parts),
                parts=tuple(parts),
                metadata={"source_sofa_config_sha256": sofa_manifest.config_sha256},
            )
            directory = run_root / artifact
            directory.mkdir(parents=True, exist_ok=True)
            temporary = directory / f"{artifact}.partial.json"
            temporary.write_text(
                json.dumps(asdict(manifest), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            temporary.replace(directory / f"{artifact}.dataset.json")
            outputs[artifact] = manifest
        return outputs
