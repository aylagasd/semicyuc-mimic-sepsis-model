#!/usr/bin/env python3
"""Run the bounded-memory full-MIMIC pipeline after CSV extraction."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Callable, TypeVar

from mimic_sepsis.chunked_features import ChunkedFeatureBuilder
from mimic_sepsis.chunked_labels import ChunkedLabelBuilder
from mimic_sepsis.chunked_landmarks import ChunkedLandmarkBuilder, PARTITIONS
from mimic_sepsis.chunked_sofa import ChunkedSofaBuilder, detect_code_version
from mimic_sepsis.deployment import preflight_protocol_status
from mimic_sepsis.chunked_sofa import validate_extract
from mimic_sepsis.resource_telemetry import (
    StageResourceMonitor, write_resource_report,
)
from mimic_sepsis.test_access import validate_test_release


T = TypeVar("T")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_dir", type=Path)
    parser.add_argument("--output-root", type=Path, default=Path("data/derived/full_pipeline"))
    parser.add_argument("--batch-size", type=int)
    parser.add_argument(
        "--compute-profile", type=Path, default=Path("config/compute_32gb.json")
    )
    parser.add_argument("--duckdb-memory-limit")
    parser.add_argument("--duckdb-temp-dir", type=Path)
    parser.add_argument("--duckdb-threads", type=int)
    parser.add_argument(
        "--resource-report", type=Path,
        help="Aggregate stage telemetry JSON (default: OUTPUT_ROOT/resource_report.json).",
    )
    parser.add_argument("--code-version")
    parser.add_argument(
        "--protocol-status", type=Path, default=Path("config/protocol_status.json")
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--materialize-test", action="store_true",
        help="Materialize the locked test partition after explicit release.",
    )
    parser.add_argument("--test-release", type=Path)
    parser.add_argument("--model-freeze", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo = Path(__file__).resolve().parents[1]
    profile_path = args.compute_profile
    if not profile_path.is_absolute():
        profile_path = repo / profile_path
    compute_profile = json.loads(profile_path.read_text(encoding="utf-8"))
    if compute_profile.get("schema_version") != 1:
        raise ValueError("Unsupported compute profile")
    batch_size = (
        args.batch_size
        if args.batch_size is not None
        else int(compute_profile["chunk_batch_size"])
    )
    duckdb_memory_limit = (
        args.duckdb_memory_limit
        or str(compute_profile["duckdb_memory_limit"])
    )
    duckdb_threads = (
        args.duckdb_threads
        if args.duckdb_threads is not None
        else int(compute_profile["maximum_parallel_workers"])
    )
    sources = validate_extract(args.source_dir)
    data_version = next(iter(sources.values())).data_version
    partitions = PARTITIONS
    if data_version != "2.2":
        protocol = json.loads(args.protocol_status.read_text(encoding="utf-8"))
        gate = preflight_protocol_status(protocol, "model")
        if not gate.ready:
            print(json.dumps(gate.to_dict(), indent=2, sort_keys=True))
            return 2
        partitions = ("development", "validation")
        if args.materialize_test:
            test_gate = preflight_protocol_status(protocol, "test")
            if not test_gate.ready:
                print(json.dumps(test_gate.to_dict(), indent=2, sort_keys=True))
                return 2
            if args.test_release is None or args.model_freeze is None:
                print(json.dumps({
                    "error": "--test-release and --model-freeze are required",
                    "test_materialized": False,
                }, indent=2, sort_keys=True))
                return 2
            try:
                validate_test_release(
                    args.test_release, args.model_freeze,
                    expected_data_version=data_version,
                )
            except (FileNotFoundError, json.JSONDecodeError, ValueError) as error:
                print(json.dumps({
                    "error": str(error), "test_materialized": False,
                }, indent=2, sort_keys=True))
                return 2
            partitions = PARTITIONS
    code_version = args.code_version or detect_code_version(repo)
    report_path = args.resource_report or args.output_root / "resource_report.json"
    profile_sha256 = hashlib.sha256(profile_path.read_bytes()).hexdigest()
    stage_measurements: list[dict] = []

    def persist_report(*, completed: bool, error_type: str | None = None) -> None:
        write_resource_report(report_path, {
            "schema_version": 1,
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
            "completed": completed,
            "error_type": error_type,
            "data_version": data_version,
            "code_version": code_version,
            "compute_profile_sha256": profile_sha256,
            "runtime": {
                "batch_size": batch_size,
                "duckdb_memory_limit": duckdb_memory_limit,
                "duckdb_threads": duckdb_threads,
                "resume": bool(args.resume),
            },
            "stages": stage_measurements,
        })

    def execute_stage(name: str, output: Path, action: Callable[[], T]) -> T:
        monitor = StageResourceMonitor(name, output)
        try:
            with monitor:
                result = action()
                if isinstance(result, dict):
                    monitor.set_counts(
                        rows=sum(int(item.rows) for item in result.values()),
                        parts=sum(len(item.parts) for item in result.values()),
                    )
                else:
                    monitor.set_counts(rows=int(result.rows), parts=len(result.parts))
                return result
        finally:
            stage_measurements.append(monitor.measurement.to_dict())
            persist_report(
                completed=False, error_type=monitor.measurement.error_type
            )

    sofa = execute_stage(
        "sofa", args.output_root / "sofa",
        lambda: ChunkedSofaBuilder(
            args.source_dir, args.output_root / "sofa",
            batch_size=batch_size, code_version=code_version,
            duckdb_memory_limit=duckdb_memory_limit,
            duckdb_temp_dir=args.duckdb_temp_dir,
            duckdb_threads=duckdb_threads,
        ).run(resume=args.resume),
    )
    sofa_run = args.output_root / "sofa" / sofa.config_sha256[:16]
    labels = execute_stage(
        "labels", args.output_root / "labels",
        lambda: ChunkedLabelBuilder(
            args.source_dir, sofa_run, args.output_root / "labels",
            rules_path=repo / "config" / "antimicrobial_rules.csv",
            infection_config_path=repo / "config" / "suspected_infection.json",
            sepsis_config_path=repo / "config" / "sepsis3.json",
            shock_config_path=repo / "config" / "septic_shock.json",
            code_version=code_version,
            duckdb_memory_limit=duckdb_memory_limit,
            duckdb_temp_dir=args.duckdb_temp_dir,
            duckdb_threads=duckdb_threads,
        ).run(resume=args.resume),
    )
    label_hash = next(iter(labels.values())).config_sha256
    label_run = args.output_root / "labels" / label_hash[:16]
    landmarks = execute_stage(
        "landmarks", args.output_root / "landmarks",
        lambda: ChunkedLandmarkBuilder(
            args.source_dir, sofa_run, label_run, args.output_root / "landmarks",
            landmark_config_path=repo / "config" / "landmarks.json",
            split_config_path=repo / "config" / "splits.json",
            code_version=code_version,
            partitions=partitions,
            allow_non_demo_test=args.materialize_test and data_version != "2.2",
            duckdb_memory_limit=duckdb_memory_limit,
            duckdb_temp_dir=args.duckdb_temp_dir,
            duckdb_threads=duckdb_threads,
        ).run(resume=args.resume),
    )
    landmark_hash = next(iter(landmarks.values())).config_sha256
    landmark_run = args.output_root / "landmarks" / landmark_hash[:16]
    features = execute_stage(
        "features", args.output_root / "features",
        lambda: ChunkedFeatureBuilder(
            args.source_dir, landmark_run, args.output_root / "features",
            feature_config_path=repo / "config" / "features.json",
            code_version=code_version,
            partitions=partitions,
            allow_non_demo_test=args.materialize_test and data_version != "2.2",
            duckdb_memory_limit=duckdb_memory_limit,
            duckdb_temp_dir=args.duckdb_temp_dir,
            duckdb_threads=duckdb_threads,
        ).run(resume=args.resume),
    )
    persist_report(completed=True)
    print(json.dumps({
        "sofa": {"run_id": sofa_run.name, "rows": sofa.rows},
        "labels": {name: item.rows for name, item in labels.items()},
        "landmarks": {name: item.rows for name, item in landmarks.items()},
        "features": {name: item.rows for name, item in features.items()},
        "compute_profile": {
            "batch_size": batch_size,
            "duckdb_memory_limit": duckdb_memory_limit,
            "duckdb_threads": duckdb_threads,
        },
        "materialized_partitions": list(partitions),
        "resource_report_written": True,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
