"""Versioned, verifiable storage for local derived data.

Derived patient-level data belong below ``data/derived`` (which must remain
outside version control).  Each Parquet file has a JSON sidecar containing
enough provenance to detect stale, incomplete, or corrupted artifacts.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Mapping

import pandas as pd


_VALID_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class ArtifactError(RuntimeError):
    """Base class for artifact storage errors."""


class ArtifactValidationError(ArtifactError):
    """Raised when an artifact and its manifest do not agree."""


@dataclass(frozen=True)
class ArtifactManifest:
    """Provenance and integrity metadata for one derived table."""

    artifact: str
    format: str
    data_version: str
    code_version: str
    rows: int
    columns: list[str]
    dtypes: dict[str, str]
    sha256: str
    config_sha256: str
    created_at_utc: str

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ArtifactManifest":
        try:
            return cls(**value)
        except (TypeError, KeyError) as exc:
            raise ArtifactValidationError("Malformed artifact manifest") from exc


def _canonical_hash(value: Mapping[str, Any] | None) -> str:
    payload = json.dumps(
        {} if value is None else value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _file_hash(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ArtifactStore:
    """Persist pandas frames as atomic Parquet artifacts with JSON manifests."""

    def __init__(self, root: str | Path = "data/derived") -> None:
        self.root = Path(root)

    def _paths(self, name: str) -> tuple[Path, Path]:
        if not _VALID_NAME.fullmatch(name):
            raise ValueError(
                "Artifact name must contain only letters, numbers, '.', '-' or '_'"
            )
        return self.root / f"{name}.parquet", self.root / f"{name}.manifest.json"

    def write_dataframe(
        self,
        name: str,
        frame: pd.DataFrame,
        *,
        data_version: str,
        code_version: str,
        config: Mapping[str, Any] | None = None,
    ) -> ArtifactManifest:
        """Atomically replace an artifact and publish its manifest last."""
        if not isinstance(frame, pd.DataFrame):
            raise TypeError("frame must be a pandas DataFrame")
        data_path, manifest_path = self._paths(name)
        self.root.mkdir(parents=True, exist_ok=True)
        data_tmp = self._temporary_path(".parquet")
        manifest_tmp = self._temporary_path(".json")
        try:
            self._write_parquet(frame, data_tmp)
            manifest = ArtifactManifest(
                artifact=name,
                format="parquet",
                data_version=str(data_version),
                code_version=str(code_version),
                rows=len(frame),
                columns=[str(column) for column in frame.columns],
                dtypes={str(column): str(dtype) for column, dtype in frame.dtypes.items()},
                sha256=_file_hash(data_tmp),
                config_sha256=_canonical_hash(config),
                created_at_utc=datetime.now(timezone.utc).isoformat(),
            )
            with manifest_tmp.open("w", encoding="utf-8") as stream:
                json.dump(asdict(manifest), stream, indent=2, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(data_tmp, data_path)
            os.replace(manifest_tmp, manifest_path)
            return manifest
        finally:
            data_tmp.unlink(missing_ok=True)
            manifest_tmp.unlink(missing_ok=True)

    def read_dataframe(
        self,
        name: str,
        *,
        validate: bool = True,
        expected_config: Mapping[str, Any] | None = None,
    ) -> pd.DataFrame:
        """Read an artifact, validating integrity and optional configuration."""
        if validate:
            self.validate(name, expected_config=expected_config)
        data_path, _ = self._paths(name)
        if not data_path.exists():
            raise FileNotFoundError(data_path)
        import duckdb

        return duckdb.sql("SELECT * FROM read_parquet(?)", params=[str(data_path)]).df()

    def read_manifest(self, name: str) -> ArtifactManifest:
        _, manifest_path = self._paths(name)
        if not manifest_path.exists():
            raise FileNotFoundError(manifest_path)
        try:
            value = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise ArtifactValidationError("Cannot read artifact manifest") from exc
        return ArtifactManifest.from_dict(value)

    def validate(
        self,
        name: str,
        *,
        expected_config: Mapping[str, Any] | None = None,
    ) -> ArtifactManifest:
        """Validate checksum, shape/schema metadata, and optional config hash."""
        data_path, _ = self._paths(name)
        manifest = self.read_manifest(name)
        if not data_path.exists():
            raise ArtifactValidationError(f"Missing data file for artifact {name!r}")
        if manifest.artifact != name or manifest.format != "parquet":
            raise ArtifactValidationError("Manifest identity or format mismatch")
        if _file_hash(data_path) != manifest.sha256:
            raise ArtifactValidationError("Artifact checksum mismatch")
        if expected_config is not None:
            if _canonical_hash(expected_config) != manifest.config_sha256:
                raise ArtifactValidationError("Artifact configuration mismatch")

        import duckdb

        description = duckdb.sql(
            "DESCRIBE SELECT * FROM read_parquet(?)", params=[str(data_path)]
        ).df()
        columns = description["column_name"].astype(str).tolist()
        rows = int(
            duckdb.sql(
                "SELECT count(*) AS n FROM read_parquet(?)", params=[str(data_path)]
            ).fetchone()[0]
        )
        if rows != manifest.rows or columns != manifest.columns:
            raise ArtifactValidationError("Artifact shape or column metadata mismatch")
        return manifest

    def _temporary_path(self, suffix: str) -> Path:
        descriptor, raw_path = tempfile.mkstemp(
            dir=self.root, prefix=".artifact-", suffix=suffix
        )
        os.close(descriptor)
        return Path(raw_path)

    @staticmethod
    def _write_parquet(frame: pd.DataFrame, path: Path) -> None:
        import duckdb

        connection = duckdb.connect()
        try:
            connection.register("_artifact_frame", frame)
            escaped = str(path).replace("'", "''")
            connection.execute(
                f"COPY _artifact_frame TO '{escaped}' "
                "(FORMAT PARQUET, COMPRESSION ZSTD)"
            )
        finally:
            connection.close()
