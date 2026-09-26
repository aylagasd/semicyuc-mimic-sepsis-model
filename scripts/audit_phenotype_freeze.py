#!/usr/bin/env python3
"""Create protected aggregate evidence for D002/D004/D010/D011 review."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mimic_sepsis.phenotype_evidence import (
    build_phenotype_evidence,
    load_validated_phenotype_source,
    write_phenotype_evidence,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "label_run",
        type=Path,
        help="demo run root/40_labels or partitioned full-pipeline label run",
    )
    parser.add_argument(
        "--protocol-status",
        type=Path,
        default=Path("config/protocol_status.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="protected JSON output (default: LABEL_RUN/audit/phenotype_freeze_evidence.json)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    status_document = json.loads(args.protocol_status.read_text(encoding="utf-8"))
    statuses = status_document.get("decisions")
    if not isinstance(statuses, dict):
        raise ValueError("protocol status lacks a decisions object")
    source = load_validated_phenotype_source(args.label_run)
    content = build_phenotype_evidence(source, protocol_status=statuses)
    output = args.output or args.label_run / "audit" / "phenotype_freeze_evidence.json"
    digest = write_phenotype_evidence(output, content)
    # Do not print counts or source paths: the protected report is reviewed locally.
    print(json.dumps({
        "clinical_status_mutated": False,
        "data_version": source.data_version,
        "report_sha256": digest,
        "source_layout": source.layout,
        "written": True,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
