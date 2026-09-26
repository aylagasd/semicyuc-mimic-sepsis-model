#!/usr/bin/env python3
"""Create protected aggregate evidence for D002 cohort-policy review."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mimic_sepsis.cohort_evidence import (
    build_cohort_policy_evidence,
    load_cohort_sources,
)
from mimic_sepsis.protected_evidence import write_protected_evidence


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_dir", type=Path)
    parser.add_argument("--data-version", required=True)
    parser.add_argument(
        "--sensitivity-config",
        type=Path,
        default=Path("config/sensitivity.json"),
    )
    parser.add_argument(
        "--protocol-status",
        type=Path,
        default=Path("config/protocol_status.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/derived/audit/cohort_policy_evidence.json"),
    )
    parser.add_argument("--memory-limit", default="1GB")
    parser.add_argument("--temp-dir", type=Path)
    parser.add_argument("--threads", type=int, default=2)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    sensitivity = json.loads(args.sensitivity_config.read_text(encoding="utf-8"))
    if sensitivity.get("schema_version") != 2:
        raise ValueError("Unsupported sensitivity configuration schema")
    protocol = json.loads(args.protocol_status.read_text(encoding="utf-8"))
    statuses = protocol.get("decisions")
    if not isinstance(statuses, dict):
        raise ValueError("protocol status lacks a decisions object")
    frames, hashes = load_cohort_sources(
        args.data_dir,
        memory_limit=args.memory_limit,
        temp_dir=args.temp_dir,
        threads=args.threads,
    )
    content = build_cohort_policy_evidence(
        frames["patients"], frames["admissions"], frames["icustays"],
        data_version=args.data_version,
        source_sha256=hashes,
        protocol_status=statuses,
        policies=sensitivity["cohort_policies"],
        minimum_age=sensitivity["cohort_minimum_age"],
    )
    digest = write_protected_evidence(args.output, content)
    print(json.dumps({
        "clinical_status_mutated": False,
        "data_version": str(args.data_version),
        "report_sha256": digest,
        "written": True,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
