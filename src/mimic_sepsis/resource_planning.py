"""Conservative, aggregate-only memory planning for pre-test analysis."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import os
from typing import Any

import pandas as pd

from .pretest_inputs import PretestInputBundle


GIB = 1024**3


def dataframe_memory_bytes(frame: pd.DataFrame) -> int:
    """Return pandas' deep resident-memory estimate for one frame."""
    return int(frame.memory_usage(index=True, deep=True).sum())


def available_memory_bytes() -> int | None:
    """Return currently available host memory without adding a dependency."""
    try:
        values = {}
        with open("/proc/meminfo", encoding="utf-8") as stream:
            for line in stream:
                key, raw = line.split(":", maxsplit=1)
                values[key] = int(raw.strip().split()[0]) * 1024
        if "MemAvailable" in values:
            return values["MemAvailable"]
    except (OSError, ValueError):
        pass
    try:
        return int(os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE"))
    except (AttributeError, OSError, TypeError, ValueError):
        return None


@dataclass(frozen=True)
class PretestMemoryAudit:
    """Aggregate engineering estimate; never contains patient-level values."""

    input_bytes: int
    estimated_peak_bytes: int
    target_ram_bytes: int
    target_budget_bytes: int
    current_available_bytes: int | None
    rows: int
    columns_loaded: int
    working_set_multiplier: float
    fixed_overhead_bytes: int
    maximum_ram_fraction: float
    ready_for_target: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def audit_pretest_memory(
    bundle: PretestInputBundle,
    *,
    target_ram_gib: float = 32,
    maximum_ram_fraction: float = 0.75,
    working_set_multiplier: float = 8,
    fixed_overhead_gib: float = 2,
) -> PretestMemoryAudit:
    """Estimate peak RAM from projected development/validation inputs.

    The multiplier is deliberately conservative: it allows for joined model
    tables, NumPy conversions, preprocessing and temporary estimator arrays.
    It is a deployment preflight, not an empirical guarantee; the first full
    run must still be monitored and recorded.
    """
    if target_ram_gib <= 0 or fixed_overhead_gib < 0:
        raise ValueError(
            "RAM and fixed overhead must be non-negative and RAM positive"
        )
    if not 0 < maximum_ram_fraction < 1:
        raise ValueError("maximum_ram_fraction must be in (0, 1)")
    if working_set_multiplier < 1:
        raise ValueError("working_set_multiplier must be at least 1")
    frames = [bundle.cohort]
    frames.extend(bundle.landmarks.values())
    frames.extend(bundle.features.values())
    input_bytes = sum(dataframe_memory_bytes(frame) for frame in frames)
    fixed_overhead_bytes = int(fixed_overhead_gib * GIB)
    estimated_peak_bytes = int(
        fixed_overhead_bytes + working_set_multiplier * input_bytes
    )
    target_ram_bytes = int(target_ram_gib * GIB)
    target_budget_bytes = int(target_ram_bytes * maximum_ram_fraction)
    return PretestMemoryAudit(
        input_bytes=input_bytes,
        estimated_peak_bytes=estimated_peak_bytes,
        target_ram_bytes=target_ram_bytes,
        target_budget_bytes=target_budget_bytes,
        current_available_bytes=available_memory_bytes(),
        rows=sum(len(frame) for frame in frames),
        columns_loaded=sum(len(frame.columns) for frame in frames),
        working_set_multiplier=float(working_set_multiplier),
        fixed_overhead_bytes=fixed_overhead_bytes,
        maximum_ram_fraction=float(maximum_ram_fraction),
        ready_for_target=estimated_peak_bytes <= target_budget_bytes,
    )
