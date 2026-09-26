"""Fail-closed validation of aggregate full-pipeline resource telemetry."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


EXPECTED_STAGES = ("sofa", "labels", "landmarks", "features")
GIB = 1024**3


@dataclass(frozen=True)
class PipelineResourceAudit:
    """Aggregate deployment decision; contains no patient-level information."""

    ready: bool
    blockers: tuple[str, ...]
    completed: bool
    stages: tuple[str, ...]
    peak_rss_bytes: int | None
    peak_swap_bytes: int | None
    target_budget_bytes: int
    runtime_matches_profile: bool
    compute_profile_matches: bool

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


def audit_pipeline_resources(
    payload: Mapping[str, Any],
    compute_profile: Mapping[str, Any],
    *,
    expected_compute_profile_sha256: str,
) -> PipelineResourceAudit:
    """Validate completeness, runtime budget, RSS and process swap."""
    if payload.get("schema_version") != 1:
        raise ValueError("Unsupported resource report schema")
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
    target_budget_bytes = int(target_ram_gib * GIB * maximum_fraction)

    blockers: list[str] = []
    completed = payload.get("completed") is True
    if not completed:
        blockers.append("pipeline:not_completed")
    if payload.get("error_type") is not None:
        blockers.append("pipeline:error_recorded")
    profile_matches = (
        payload.get("compute_profile_sha256") == expected_compute_profile_sha256
    )
    if not profile_matches:
        blockers.append("compute_profile:sha256_mismatch")

    runtime = payload.get("runtime")
    if not isinstance(runtime, Mapping):
        raise ValueError("Resource report runtime must be an object")
    expected_runtime = {
        "batch_size": int(compute_profile["chunk_batch_size"]),
        "duckdb_memory_limit": str(compute_profile["duckdb_memory_limit"]).upper(),
        "duckdb_threads": int(compute_profile["maximum_parallel_workers"]),
    }
    observed_runtime = {
        "batch_size": runtime.get("batch_size"),
        "duckdb_memory_limit": str(runtime.get("duckdb_memory_limit", "")).upper(),
        "duckdb_threads": runtime.get("duckdb_threads"),
    }
    runtime_matches = observed_runtime == expected_runtime
    if not runtime_matches:
        blockers.append("runtime:profile_mismatch")

    raw_stages = payload.get("stages")
    if not isinstance(raw_stages, list):
        raise ValueError("Resource report stages must be a list")
    stage_names: list[str] = []
    rss_values: list[int] = []
    swap_values: list[int] = []
    for item in raw_stages:
        if not isinstance(item, Mapping):
            raise ValueError("Every resource stage must be an object")
        name = str(item.get("stage", ""))
        stage_names.append(name)
        if item.get("status") != "completed" or item.get("error_type") is not None:
            blockers.append(f"stage:{name or 'unknown'}:not_completed")
        try:
            rows = int(item["rows"])
            parts = int(item["parts"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Stage {name or 'unknown'} lacks aggregate counts") from exc
        if rows < 0 or parts <= 0:
            blockers.append(f"stage:{name or 'unknown'}:invalid_counts")
        rss = item.get("peak_rss_bytes")
        if rss is None:
            blockers.append(f"stage:{name or 'unknown'}:rss_unavailable")
        else:
            rss_values.append(int(rss))
        swap = item.get("peak_swap_bytes")
        if swap is None:
            blockers.append(f"stage:{name or 'unknown'}:swap_unavailable")
        else:
            swap_values.append(int(swap))
    stages = tuple(stage_names)
    if stages != EXPECTED_STAGES:
        blockers.append("stages:unexpected_sequence")
    peak_rss = max(rss_values) if rss_values else None
    peak_swap = max(swap_values) if swap_values else None
    if peak_rss is not None and peak_rss > target_budget_bytes:
        blockers.append("memory:rss_budget_exceeded")
    if peak_swap is not None and peak_swap > 0:
        blockers.append("memory:swap_observed")
    unique_blockers = tuple(dict.fromkeys(blockers))
    return PipelineResourceAudit(
        ready=not unique_blockers,
        blockers=unique_blockers,
        completed=completed,
        stages=stages,
        peak_rss_bytes=peak_rss,
        peak_swap_bytes=peak_swap,
        target_budget_bytes=target_budget_bytes,
        runtime_matches_profile=runtime_matches,
        compute_profile_matches=profile_matches,
    )
