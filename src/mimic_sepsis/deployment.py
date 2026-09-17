"""Credential-free preflight checks for a full MIMIC-IV file distribution."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import csv
import gzip
from pathlib import Path
import shutil
from typing import Mapping


REQUIRED_FILE_COLUMNS: Mapping[str, tuple[str, ...]] = {
    "hosp/patients.csv.gz": ("subject_id", "anchor_age", "anchor_year"),
    "hosp/admissions.csv.gz": ("subject_id", "hadm_id"),
    "hosp/labevents.csv.gz": (
        "subject_id", "hadm_id", "itemid", "charttime", "storetime", "valuenum"
    ),
    "hosp/prescriptions.csv.gz": ("subject_id", "hadm_id", "pharmacy_id"),
    "hosp/emar.csv.gz": ("subject_id", "hadm_id", "pharmacy_id", "charttime"),
    "hosp/microbiologyevents.csv.gz": (
        "subject_id", "hadm_id", "micro_specimen_id", "charttime"
    ),
    "icu/icustays.csv.gz": ("subject_id", "hadm_id", "stay_id", "intime", "outtime"),
    "icu/chartevents.csv.gz": ("subject_id", "hadm_id", "stay_id", "itemid", "charttime"),
    "icu/inputevents.csv.gz": ("subject_id", "hadm_id", "stay_id", "itemid", "starttime"),
    "icu/outputevents.csv.gz": ("subject_id", "hadm_id", "stay_id", "itemid", "charttime"),
    "icu/procedureevents.csv.gz": ("subject_id", "hadm_id", "stay_id", "itemid", "starttime"),
}


@dataclass(frozen=True)
class FilePreflightReport:
    root: str
    required_files: int
    present_files: int
    compressed_bytes: int
    free_bytes: int
    minimum_free_bytes: int
    missing_files: tuple[str, ...]
    unreadable_files: tuple[str, ...]
    missing_columns: Mapping[str, tuple[str, ...]]

    @property
    def ready(self) -> bool:
        return (
            not self.missing_files
            and not self.unreadable_files
            and not any(self.missing_columns.values())
            and self.free_bytes >= self.minimum_free_bytes
        )

    def to_dict(self) -> dict:
        return {**asdict(self), "ready": self.ready}


def _gzip_header(path: Path) -> tuple[str, ...]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as stream:
        return tuple(next(csv.reader(stream)))


def preflight_mimic_files(
    data_dir: str | Path,
    *,
    minimum_free_gb: float = 0,
    requirements: Mapping[str, tuple[str, ...]] = REQUIRED_FILE_COLUMNS,
) -> FilePreflightReport:
    """Inspect file presence and CSV headers without reading patient rows."""
    if minimum_free_gb < 0:
        raise ValueError("minimum_free_gb must be non-negative")
    root = Path(data_dir).resolve()
    missing_files, unreadable_files = [], []
    missing_columns: dict[str, tuple[str, ...]] = {}
    compressed_bytes = present = 0
    for relative, required_columns in requirements.items():
        path = root / relative
        if not path.is_file():
            missing_files.append(relative)
            continue
        present += 1
        compressed_bytes += path.stat().st_size
        try:
            columns = set(_gzip_header(path))
        except (OSError, UnicodeError, StopIteration, csv.Error):
            unreadable_files.append(relative)
            continue
        missing_columns[relative] = tuple(sorted(set(required_columns) - columns))
    free_bytes = shutil.disk_usage(root if root.exists() else root.parent).free
    return FilePreflightReport(
        root=str(root),
        required_files=len(requirements),
        present_files=present,
        compressed_bytes=compressed_bytes,
        free_bytes=free_bytes,
        minimum_free_bytes=int(minimum_free_gb * 1024**3),
        missing_files=tuple(sorted(missing_files)),
        unreadable_files=tuple(sorted(unreadable_files)),
        missing_columns=missing_columns,
    )
