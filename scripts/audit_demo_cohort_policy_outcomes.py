#!/usr/bin/env python3
"""Compare protected downstream counts from three complete demo policy runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mimic_sepsis.cohort_evidence import build_demo_policy_outcome_evidence
from mimic_sepsis.protected_evidence import write_protected_evidence
from build_demo_sofa_incremental import canonical_config


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--first-per-admission", type=Path, required=True)
    parser.add_argument("--first-per-patient", type=Path, required=True)
    parser.add_argument("--all", dest="all_stays", type=Path, required=True)
    parser.add_argument(
        "--protocol-status", type=Path,
        default=Path("config/protocol_status.json"),
    )
    parser.add_argument(
        "--output", type=Path,
        default=Path(
            "data/derived/audit/cohort_policy_downstream_evidence.json"
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    policies = ("first_per_admission", "first_per_patient", "all")
    roots = dict(zip(
        policies,
        (args.first_per_admission, args.first_per_patient, args.all_stays),
        strict=True,
    ))
    configs = {policy: canonical_config(policy) for policy in policies}
    protocol = json.loads(args.protocol_status.read_text(encoding="utf-8"))
    content = build_demo_policy_outcome_evidence(
        roots,
        expected_configs=configs,
        protocol_status=protocol.get("decisions", {}),
    )
    digest = write_protected_evidence(args.output, content)
    print(json.dumps({
        "clinical_status_mutated": False,
        "data_version": "2.2",
        "report_sha256": digest,
        "written": True,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
