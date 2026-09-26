"""Aggregate, patient-safe resource telemetry for long local pipeline stages."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from threading import Event, Thread
from time import perf_counter
from typing import Any


def process_memory_bytes() -> tuple[int | None, int | None]:
    """Return current resident and swapped memory on Linux."""
    rss = None
    swap = None
    try:
        with Path("/proc/self/status").open(encoding="utf-8") as stream:
            for line in stream:
                if line.startswith("VmRSS:"):
                    rss = int(line.split()[1]) * 1024
                elif line.startswith("VmSwap:"):
                    swap = int(line.split()[1]) * 1024
    except (OSError, IndexError, ValueError):
        return None, None
    return rss, swap


def process_rss_bytes() -> int | None:
    """Return current resident memory on Linux without adding a dependency."""
    return process_memory_bytes()[0]


def process_io_bytes() -> tuple[int, int] | None:
    """Return process-level physical read/write byte counters when available."""
    try:
        values: dict[str, int] = {}
        with Path("/proc/self/io").open(encoding="utf-8") as stream:
            for line in stream:
                key, raw = line.split(":", maxsplit=1)
                values[key] = int(raw.strip())
        return values["read_bytes"], values["write_bytes"]
    except (OSError, KeyError, ValueError):
        return None


def directory_bytes(root: Path) -> int:
    """Sum regular-file sizes below a stage directory using metadata only."""
    if not root.exists():
        return 0
    total = 0
    for directory, _, files in os.walk(root):
        for name in files:
            try:
                path = Path(directory) / name
                if path.is_file():
                    total += path.stat().st_size
            except OSError:
                continue
    return total


@dataclass
class StageResourceMeasurement:
    """Safe aggregate counters for one pipeline stage."""

    stage: str
    status: str = "running"
    started_at_utc: str = ""
    elapsed_seconds: float = 0.0
    starting_rss_bytes: int | None = None
    peak_rss_bytes: int | None = None
    starting_swap_bytes: int | None = None
    peak_swap_bytes: int | None = None
    read_bytes: int | None = None
    write_bytes: int | None = None
    output_bytes: int = 0
    output_bytes_added: int = 0
    rows: int | None = None
    parts: int | None = None
    error_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class StageResourceMonitor:
    """Sample RSS while measuring elapsed, I/O and output size for one stage."""

    def __init__(
        self, stage: str, output_root: Path, *, sample_interval_seconds: float = 0.1
    ) -> None:
        if not stage or sample_interval_seconds <= 0:
            raise ValueError("stage and a positive sample interval are required")
        self.output_root = Path(output_root)
        self.sample_interval_seconds = float(sample_interval_seconds)
        self.measurement = StageResourceMeasurement(stage=stage)
        self._stop = Event()
        self._thread: Thread | None = None
        self._started = 0.0
        self._starting_io: tuple[int, int] | None = None
        self._starting_output_bytes = 0

    def __enter__(self) -> "StageResourceMonitor":
        self.measurement.started_at_utc = datetime.now(timezone.utc).isoformat()
        self._started = perf_counter()
        self._starting_io = process_io_bytes()
        self._starting_output_bytes = directory_bytes(self.output_root)
        rss, swap = process_memory_bytes()
        self.measurement.starting_rss_bytes = rss
        self.measurement.peak_rss_bytes = self.measurement.starting_rss_bytes
        self.measurement.starting_swap_bytes = swap
        self.measurement.peak_swap_bytes = self.measurement.starting_swap_bytes
        self._thread = Thread(target=self._sample_until_stopped, daemon=True)
        self._thread.start()
        return self

    def set_counts(self, *, rows: int, parts: int) -> None:
        """Attach only aggregate output cardinalities to the measurement."""
        self.measurement.rows = int(rows)
        self.measurement.parts = int(parts)

    def _sample(self) -> None:
        rss, swap = process_memory_bytes()
        if rss is not None:
            previous = self.measurement.peak_rss_bytes
            self.measurement.peak_rss_bytes = rss if previous is None else max(
                previous, rss
            )
        if swap is not None:
            previous_swap = self.measurement.peak_swap_bytes
            self.measurement.peak_swap_bytes = (
                swap if previous_swap is None else max(previous_swap, swap)
            )

    def _sample_until_stopped(self) -> None:
        while not self._stop.wait(self.sample_interval_seconds):
            self._sample()

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self.sample_interval_seconds * 2))
        self._sample()
        self.measurement.elapsed_seconds = round(perf_counter() - self._started, 6)
        ending_io = process_io_bytes()
        if self._starting_io is not None and ending_io is not None:
            self.measurement.read_bytes = max(0, ending_io[0] - self._starting_io[0])
            self.measurement.write_bytes = max(0, ending_io[1] - self._starting_io[1])
        self.measurement.output_bytes = directory_bytes(self.output_root)
        self.measurement.output_bytes_added = max(
            0, self.measurement.output_bytes - self._starting_output_bytes
        )
        self.measurement.status = "failed" if exc_type is not None else "completed"
        self.measurement.error_type = None if exc_type is None else exc_type.__name__
        return False


def write_resource_report(path: Path, payload: dict[str, Any]) -> None:
    """Atomically persist one aggregate report; never include source paths or rows."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".partial")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(target)
