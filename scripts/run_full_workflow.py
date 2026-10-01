#!/usr/bin/env python3
"""Orchestrate the bounded-memory workflow for an authorized MIMIC-IV copy."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import sys
from typing import Callable, Sequence

from mimic_sepsis.cohort import StayPolicy
from mimic_sepsis.deployment import preflight_protocol_status


STAGES = ("preflight", "extract", "pipeline", "validate")


@dataclass(frozen=True)
class WorkflowCommand:
    """One auditable subprocess in the full-data workflow."""

    stage: str
    argv: tuple[str, ...]


class WorkflowStageError(RuntimeError):
    """A stage failed after zero or more earlier stages completed."""

    def __init__(self, stage: str, exit_code: int, completed: Sequence[str]):
        super().__init__(stage)
        self.stage = stage
        self.exit_code = exit_code
        self.completed = tuple(completed)


def _load_object(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path.name}")
    return payload


def build_workflow_commands(
    *,
    repo: Path,
    python: str,
    data_dir: Path,
    data_version: str,
    work_root: Path,
    temp_dir: Path,
    compute_profile: Path,
    minimum_work_free_gb: float,
    minimum_temp_free_gb: float,
    minimum_source_free_gb: float,
    minimum_age: int,
    stay_policy: str,
    through: str,
    resume: bool,
) -> tuple[WorkflowCommand, ...]:
    """Build deterministic commands without executing or reading clinical rows."""
    if through not in STAGES:
        raise ValueError(f"Unknown workflow stage: {through}")
    profile = _load_object(compute_profile)
    if profile.get("schema_version") != 1:
        raise ValueError("Unsupported compute profile")
    memory_limit = str(profile["duckdb_memory_limit"])
    threads = int(profile["maximum_parallel_workers"])
    if min(
        minimum_work_free_gb,
        minimum_temp_free_gb,
        minimum_source_free_gb,
    ) < 0:
        raise ValueError("minimum free disk requirements must be non-negative")
    if minimum_age < 18:
        raise ValueError("minimum_age must be at least 18")

    scripts = repo / "scripts"
    extract_root = work_root / "full_extract"
    pipeline_root = work_root / "full_pipeline"
    commands = [WorkflowCommand("host_preflight", (
        python,
        str(scripts / "preflight_compute_host.py"),
        "--work-path",
        str(work_root),
        "--temp-path",
        str(temp_dir),
        "--compute-profile",
        str(compute_profile),
        "--minimum-work-free-gb",
        str(minimum_work_free_gb),
        "--minimum-temp-free-gb",
        str(minimum_temp_free_gb),
    )), WorkflowCommand("data_preflight", (
        python,
        str(scripts / "preflight_mimic_files.py"),
        str(data_dir),
        "--minimum-free-gb",
        str(minimum_source_free_gb),
    ))]
    if STAGES.index(through) >= STAGES.index("extract"):
        argv = [
            python,
            str(scripts / "extract_full_mimic.py"),
            str(data_dir),
            "--data-version",
            data_version,
            "--minimum-age",
            str(minimum_age),
            "--stay-policy",
            stay_policy,
            "--output-dir",
            str(extract_root),
            "--temp-dir",
            str(temp_dir),
            "--memory-limit",
            memory_limit,
            "--threads",
            str(threads),
        ]
        if resume:
            argv.append("--resume")
        commands.append(WorkflowCommand("extract", tuple(argv)))
    if STAGES.index(through) >= STAGES.index("pipeline"):
        argv = [
            python,
            str(scripts / "build_full_pipeline_chunked.py"),
            str(extract_root),
            "--output-root",
            str(pipeline_root),
            "--compute-profile",
            str(compute_profile),
            "--duckdb-temp-dir",
            str(temp_dir),
        ]
        if resume:
            argv.append("--resume")
        commands.append(WorkflowCommand("pipeline", tuple(argv)))
    if through == "validate":
        commands.append(WorkflowCommand("validate", (
            python,
            str(scripts / "validate_pipeline_resources.py"),
            str(pipeline_root / "resource_report.json"),
            "--compute-profile",
            str(compute_profile),
        )))
    return tuple(commands)


def run_workflow_commands(
    commands: Sequence[WorkflowCommand],
    *,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> tuple[str, ...]:
    """Run commands in order and stop at the first failed stage."""
    completed: list[str] = []
    for command in commands:
        result = runner(command.argv, check=False)
        if result.returncode != 0:
            raise WorkflowStageError(command.stage, result.returncode, completed)
        completed.append(command.stage)
    return tuple(completed)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_dir", type=Path)
    parser.add_argument("--data-version", required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--temp-dir", type=Path)
    parser.add_argument(
        "--compute-profile", type=Path, default=Path("config/compute_32gb.json")
    )
    parser.add_argument(
        "--protocol-status", type=Path, default=Path("config/protocol_status.json")
    )
    parser.add_argument(
        "--minimum-work-free-gb", "--minimum-free-gb",
        dest="minimum_work_free_gb", type=float, default=0,
        help="Derived-data disk reserve (--minimum-free-gb is a compatible alias).",
    )
    parser.add_argument(
        "--minimum-temp-free-gb", type=float,
        help="Temporary-disk reserve; defaults to --minimum-work-free-gb.",
    )
    parser.add_argument(
        "--minimum-source-free-gb", type=float, default=0,
        help="Optional reserve on the read-only source-data filesystem.",
    )
    parser.add_argument("--minimum-age", type=int, default=18)
    parser.add_argument(
        "--stay-policy",
        choices=tuple(policy.value for policy in StayPolicy),
        default=StayPolicy.FIRST_PER_ADMISSION.value,
    )
    parser.add_argument("--through", choices=STAGES, default="validate")
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo = Path(__file__).resolve().parents[1]
    profile_path = args.compute_profile
    if not profile_path.is_absolute():
        profile_path = repo / profile_path
    protocol_path = args.protocol_status
    if not protocol_path.is_absolute():
        protocol_path = repo / protocol_path
    work_root = args.work_root.resolve()
    temp_dir = (args.temp_dir or work_root / "duckdb_tmp").resolve()

    try:
        if STAGES.index(args.through) >= STAGES.index("pipeline") and args.data_version != "2.2":
            gate = preflight_protocol_status(_load_object(protocol_path), "model")
            if not gate.ready:
                print(json.dumps({
                    "error": "protocol_gate_blocked",
                    "hint": "Resolve the listed decisions or use --through extract.",
                    **gate.to_dict(),
                }, indent=2, sort_keys=True))
                return 2
        work_root.mkdir(parents=True, exist_ok=True)
        temp_dir.mkdir(parents=True, exist_ok=True)
        commands = build_workflow_commands(
            repo=repo,
            python=sys.executable,
            data_dir=args.data_dir.resolve(),
            data_version=args.data_version,
            work_root=work_root,
            temp_dir=temp_dir,
            compute_profile=profile_path,
            minimum_work_free_gb=args.minimum_work_free_gb,
            minimum_temp_free_gb=(
                args.minimum_work_free_gb
                if args.minimum_temp_free_gb is None
                else args.minimum_temp_free_gb
            ),
            minimum_source_free_gb=args.minimum_source_free_gb,
            minimum_age=args.minimum_age,
            stay_policy=args.stay_policy,
            through=args.through,
            resume=args.resume,
        )
        completed = run_workflow_commands(commands)
    except WorkflowStageError as error:
        print(json.dumps({
            "completed_stages": error.completed,
            "error": "workflow_stage_failed",
            "exit_code": error.exit_code,
            "stage": error.stage,
        }, indent=2, sort_keys=True))
        return int(error.exit_code) or 2
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({
            "error": "workflow_configuration_failed",
            "error_type": type(error).__name__,
        }, indent=2, sort_keys=True))
        return 2

    print(json.dumps({
        "completed_stages": completed,
        "data_version": args.data_version,
        "resume": bool(args.resume),
        "status": "completed",
        "through": args.through,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
