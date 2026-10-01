"""Aggregate-only host checks for the bounded full-data workflow."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import os
from pathlib import Path
import shutil
from typing import Any, Mapping


GIB = 1024**3


@dataclass(frozen=True)
class HostPreflightReport:
    """Capacity report containing system measurements but no clinical data."""

    ready: bool
    blockers: tuple[str, ...]
    total_memory_bytes: int | None
    available_memory_bytes: int | None
    target_budget_bytes: int
    logical_cpu_count: int | None
    required_workers: int
    work_free_bytes: int
    minimum_work_free_bytes: int
    temp_free_bytes: int
    minimum_temp_free_bytes: int
    work_writable: bool
    temp_writable: bool
    shared_work_temp_filesystem: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _positive_number(value: Any, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if result <= 0:
        raise ValueError(f"{name} must be positive")
    return result


def audit_compute_host(
    compute_profile: Mapping[str, Any],
    *,
    total_memory_bytes: int | None,
    available_memory_bytes: int | None,
    logical_cpu_count: int | None,
    work_free_bytes: int,
    temp_free_bytes: int,
    work_writable: bool,
    temp_writable: bool,
    shared_work_temp_filesystem: bool,
    minimum_work_free_gib: float = 0,
    minimum_temp_free_gib: float = 0,
) -> HostPreflightReport:
    """Compare host capacity with a compute profile and explicit disk reserves."""
    if compute_profile.get("schema_version") != 1:
        raise ValueError("Unsupported compute profile schema")
    target_ram_gib = _positive_number(
        compute_profile.get("target_ram_gib"), "target_ram_gib"
    )
    maximum_fraction = _positive_number(
        compute_profile.get("maximum_ram_fraction"), "maximum_ram_fraction"
    )
    if maximum_fraction >= 1:
        raise ValueError("maximum_ram_fraction must be below one")
    required_workers = int(
        _positive_number(
            compute_profile.get("maximum_parallel_workers"),
            "maximum_parallel_workers",
        )
    )
    if minimum_work_free_gib < 0 or minimum_temp_free_gib < 0:
        raise ValueError("Minimum free disk requirements must be non-negative")
    if work_free_bytes < 0 or temp_free_bytes < 0:
        raise ValueError("Observed free disk must be non-negative")

    target_budget_bytes = int(target_ram_gib * GIB * maximum_fraction)
    minimum_work_free_bytes = int(minimum_work_free_gib * GIB)
    minimum_temp_free_bytes = int(minimum_temp_free_gib * GIB)
    blockers: list[str] = []
    if total_memory_bytes is None:
        blockers.append("memory:total_unavailable")
    elif total_memory_bytes < target_budget_bytes:
        blockers.append("memory:total_below_budget")
    if available_memory_bytes is None:
        blockers.append("memory:available_unavailable")
    elif available_memory_bytes < target_budget_bytes:
        blockers.append("memory:available_below_budget")
    if logical_cpu_count is None:
        blockers.append("cpu:count_unavailable")
    elif logical_cpu_count < required_workers:
        blockers.append("cpu:workers_unavailable")
    if not work_writable:
        blockers.append("work:path_not_writable")
    if not temp_writable:
        blockers.append("temp:path_not_writable")
    if work_free_bytes < minimum_work_free_bytes:
        blockers.append("work:free_disk_below_minimum")
    if temp_free_bytes < minimum_temp_free_bytes:
        blockers.append("temp:free_disk_below_minimum")
    if (
        shared_work_temp_filesystem
        and min(work_free_bytes, temp_free_bytes)
        < minimum_work_free_bytes + minimum_temp_free_bytes
    ):
        blockers.append("shared:free_disk_below_combined_minimum")

    unique_blockers = tuple(dict.fromkeys(blockers))
    return HostPreflightReport(
        ready=not unique_blockers,
        blockers=unique_blockers,
        total_memory_bytes=total_memory_bytes,
        available_memory_bytes=available_memory_bytes,
        target_budget_bytes=target_budget_bytes,
        logical_cpu_count=logical_cpu_count,
        required_workers=required_workers,
        work_free_bytes=int(work_free_bytes),
        minimum_work_free_bytes=minimum_work_free_bytes,
        temp_free_bytes=int(temp_free_bytes),
        minimum_temp_free_bytes=minimum_temp_free_bytes,
        work_writable=bool(work_writable),
        temp_writable=bool(temp_writable),
        shared_work_temp_filesystem=bool(shared_work_temp_filesystem),
    )


def host_memory_bytes() -> tuple[int | None, int | None]:
    """Return total and currently available memory without extra dependencies."""
    try:
        values: dict[str, int] = {}
        with open("/proc/meminfo", encoding="utf-8") as stream:
            for line in stream:
                key, raw = line.split(":", maxsplit=1)
                values[key] = int(raw.strip().split()[0]) * 1024
        if "MemTotal" in values and "MemAvailable" in values:
            return values["MemTotal"], values["MemAvailable"]
    except (OSError, ValueError):
        pass
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        return (
            int(os.sysconf("SC_PHYS_PAGES") * page_size),
            int(os.sysconf("SC_AVPHYS_PAGES") * page_size),
        )
    except (AttributeError, OSError, TypeError, ValueError):
        return None, None


def _existing_anchor(path: Path) -> Path:
    candidate = path.resolve()
    while not candidate.exists():
        if candidate == candidate.parent:
            raise FileNotFoundError(path)
        candidate = candidate.parent
    if not candidate.is_dir():
        candidate = candidate.parent
    return candidate


def inspect_compute_host(
    compute_profile: Mapping[str, Any],
    *,
    work_path: str | Path,
    temp_path: str | Path,
    minimum_work_free_gib: float = 0,
    minimum_temp_free_gib: float = 0,
) -> HostPreflightReport:
    """Collect non-clinical host measurements and apply the capacity audit."""
    work_anchor = _existing_anchor(Path(work_path))
    temp_anchor = _existing_anchor(Path(temp_path))
    total_memory, available_memory = host_memory_bytes()
    return audit_compute_host(
        compute_profile,
        total_memory_bytes=total_memory,
        available_memory_bytes=available_memory,
        logical_cpu_count=os.cpu_count(),
        work_free_bytes=shutil.disk_usage(work_anchor).free,
        temp_free_bytes=shutil.disk_usage(temp_anchor).free,
        work_writable=os.access(work_anchor, os.W_OK | os.X_OK),
        temp_writable=os.access(temp_anchor, os.W_OK | os.X_OK),
        shared_work_temp_filesystem=(
            work_anchor.stat().st_dev == temp_anchor.stat().st_dev
        ),
        minimum_work_free_gib=minimum_work_free_gib,
        minimum_temp_free_gib=minimum_temp_free_gib,
    )
