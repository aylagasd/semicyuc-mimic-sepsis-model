"""Bounded-memory SOFA construction from the reduced full-MIMIC extract."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any

import duckdb
import pandas as pd

from .artifacts import ArtifactStore, ArtifactValidationError
from .full_extract import ExtractManifest, _hash_file, _sql_path
from .sofa_demo import build_demo_hourly_sofa


SOURCE_ARTIFACTS = (
    "cohort_stays",
    "chartevents_reduced",
    "labevents_reduced",
    "inputevents_reduced",
    "outputevents_reduced",
    "procedureevents_reduced",
)


@dataclass(frozen=True)
class PartitionedDatasetManifest:
    """Integrity metadata for an ordered collection of Parquet parts."""

    artifact: str
    data_version: str
    config_sha256: str
    rows: int
    parts: tuple[dict[str, Any], ...]
    metadata: dict[str, Any]

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "PartitionedDatasetManifest":
        try:
            return cls(**{
                **value, "parts": tuple(value["parts"]),
                "metadata": dict(value.get("metadata", {})),
            })
        except (KeyError, TypeError) as exc:
            raise ArtifactValidationError("Malformed partitioned dataset manifest") from exc


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def detect_code_version(repo: Path) -> str:
    """Return the current Git identity, including tracked dirty state."""
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"], cwd=repo,
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"], cwd=repo,
            check=True, capture_output=True, text=True,
        ).stdout
        return commit + ("-DIRTY" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def validate_extract(source_dir: Path) -> dict[str, ExtractManifest]:
    """Validate all required reduced artifacts without reading clinical rows."""
    result: dict[str, ExtractManifest] = {}
    config_hashes: set[str] = set()
    versions: set[str] = set()
    for name in SOURCE_ARTIFACTS:
        data_path = source_dir / f"{name}.parquet"
        manifest_path = source_dir / f"{name}.manifest.json"
        if not data_path.is_file() or not manifest_path.is_file():
            raise FileNotFoundError(f"Missing reduced artifact or manifest: {name}")
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest = ExtractManifest(**{**raw, "columns": tuple(raw["columns"])})
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ArtifactValidationError(f"Malformed extract manifest: {name}") from exc
        if manifest.artifact != name or _hash_file(data_path) != manifest.sha256:
            raise ArtifactValidationError(f"Extract checksum mismatch: {name}")
        result[name] = manifest
        config_hashes.add(manifest.config_sha256)
        versions.add(manifest.data_version)
    if len(config_hashes) != 1 or len(versions) != 1:
        raise ArtifactValidationError("Reduced artifacts come from different runs")
    return result


def validate_partitioned_dataset(
    run_root: Path, artifact: str
) -> PartitionedDatasetManifest:
    """Validate a dataset manifest and every listed Parquet part."""
    manifest_path = Path(run_root) / f"{artifact}.dataset.json"
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest = PartitionedDatasetManifest.from_dict(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise ArtifactValidationError(
            f"Cannot read partitioned dataset manifest: {artifact}"
        ) from exc
    if manifest.artifact != artifact:
        raise ArtifactValidationError("Partitioned dataset identity mismatch")
    total = 0
    seen: set[str] = set()
    for index, item in enumerate(manifest.parts):
        try:
            name, rows, sha256 = item["name"], int(item["rows"]), item["sha256"]
        except (KeyError, TypeError, ValueError) as exc:
            raise ArtifactValidationError("Malformed partition entry") from exc
        if name in seen or not re.fullmatch(r"part-\d{5}", name):
            raise ArtifactValidationError("Invalid or duplicate partition name")
        if name != f"part-{index:05d}":
            raise ArtifactValidationError("Partitions are not in canonical order")
        seen.add(name)
        path = Path(run_root) / "parts" / f"{name}.parquet"
        if not path.is_file() or _hash_file(path) != sha256:
            raise ArtifactValidationError(f"Partition checksum mismatch: {name}")
        actual_rows = int(
            duckdb.sql("SELECT count(*) FROM read_parquet(?)", params=[str(path)])
            .fetchone()[0]
        )
        if actual_rows != rows:
            raise ArtifactValidationError(f"Partition row count mismatch: {name}")
        total += rows
    if total != manifest.rows:
        raise ArtifactValidationError("Partitioned dataset total row count mismatch")
    return manifest


class ChunkedSofaBuilder:
    """Build SOFA independently for deterministic groups of ICU stays.

    Only one cohort batch and its already-filtered source rows enter pandas at
    a time. Each batch is an independently checksummed artifact, so interrupted
    runs can resume without trusting incomplete output.
    """

    def __init__(
        self,
        source_dir: Path,
        output_root: Path,
        *,
        batch_size: int = 250,
        code_version: str = "unknown",
    ) -> None:
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        self.source_dir = Path(source_dir)
        self.output_root = Path(output_root)
        self.batch_size = int(batch_size)
        self.code_version = str(code_version)

    def _configuration(self, sources: dict[str, ExtractManifest]) -> dict[str, Any]:
        return {
            "backend": "duckdb-filtered-pandas-batches",
            "chunked_sofa_schema_version": 1,
            "batch_size": self.batch_size,
            "code_version": self.code_version,
            "source_config_sha256": next(iter(sources.values())).config_sha256,
            "source_sha256": {name: item.sha256 for name, item in sources.items()},
        }

    def _read_batch(self, connection: duckdb.DuckDBPyConnection, name: str) -> pd.DataFrame:
        path = _sql_path(self.source_dir / f"{name}.parquet")
        if name == "labevents_reduced":
            join = "USING (subject_id, hadm_id)"
        else:
            join = "USING (stay_id)"
        return connection.execute(
            f"SELECT source.* FROM read_parquet('{path}') source "
            f"JOIN _batch {join}"
        ).fetchdf()

    def run(self, *, resume: bool = False) -> PartitionedDatasetManifest:
        sources = validate_extract(self.source_dir)
        config = self._configuration(sources)
        config_hash = _canonical_hash(config)
        run_root = self.output_root / config_hash[:16]
        part_store = ArtifactStore(run_root / "parts")
        dataset_path = run_root / "sofa_hourly.dataset.json"
        data_version = next(iter(sources.values())).data_version

        connection = duckdb.connect()
        parts: list[dict[str, Any]] = []
        try:
            cohort_path = _sql_path(self.source_dir / "cohort_stays.parquet")
            stay_ids = [
                int(row[0]) for row in connection.execute(
                    f"SELECT stay_id FROM read_parquet('{cohort_path}') "
                    "ORDER BY subject_id, intime, stay_id"
                ).fetchall()
            ]
            for batch_index, start in enumerate(range(0, len(stay_ids), self.batch_size)):
                batch_ids = stay_ids[start:start + self.batch_size]
                part_name = f"part-{batch_index:05d}"
                part_config = {**config, "batch_index": batch_index}
                if resume:
                    try:
                        manifest = part_store.validate(
                            part_name, expected_config=part_config
                        )
                        parts.append({
                            "name": part_name, "rows": manifest.rows,
                            "sha256": manifest.sha256,
                        })
                        continue
                    except (FileNotFoundError, ArtifactValidationError):
                        pass

                id_frame = pd.DataFrame({"stay_id": batch_ids})
                connection.register("_batch_ids", id_frame)
                cohort = connection.execute(
                    f"SELECT cohort.* FROM read_parquet('{cohort_path}') cohort "
                    "JOIN _batch_ids USING (stay_id) "
                    "ORDER BY cohort.subject_id, cohort.intime, cohort.stay_id"
                ).fetchdf()
                connection.register(
                    "_batch", cohort[["subject_id", "hadm_id", "stay_id"]]
                )
                tables = {
                    "icustays": cohort[
                        ["subject_id", "hadm_id", "stay_id", "intime", "outtime"]
                    ],
                    "chartevents": self._read_batch(connection, "chartevents_reduced"),
                    "labevents": self._read_batch(connection, "labevents_reduced"),
                    "inputevents": self._read_batch(connection, "inputevents_reduced"),
                    "outputevents": self._read_batch(connection, "outputevents_reduced"),
                    "procedureevents": self._read_batch(
                        connection, "procedureevents_reduced"
                    ),
                }
                sofa = build_demo_hourly_sofa(**tables).sort_values(
                    ["subject_id", "endtime", "stay_id", "hr"]
                ).reset_index(drop=True)
                manifest = part_store.write_dataframe(
                    part_name,
                    sofa,
                    data_version=data_version,
                    code_version=self.code_version,
                    config=part_config,
                )
                parts.append({
                    "name": part_name, "rows": manifest.rows,
                    "sha256": manifest.sha256,
                })
        finally:
            connection.close()

        result = PartitionedDatasetManifest(
            artifact="sofa_hourly",
            data_version=data_version,
            config_sha256=config_hash,
            rows=sum(int(part["rows"]) for part in parts),
            parts=tuple(parts),
            metadata={"batch_size": self.batch_size, "cohort_stays": len(stay_ids)},
        )
        run_root.mkdir(parents=True, exist_ok=True)
        temporary = dataset_path.with_suffix(".partial.json")
        temporary.write_text(
            json.dumps(asdict(result), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(dataset_path)
        return result
