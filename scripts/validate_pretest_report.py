#!/usr/bin/env python3
"""Verify a persisted aggregate pre-test report without patient-level output."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mimic_sepsis.artifacts import ArtifactError
from mimic_sepsis.report_artifacts import REPORT_TABLES, read_aggregate_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "report_root", type=Path,
        help="Directory containing aggregate_report.manifest.json.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        report, manifest = read_aggregate_report(args.report_root)
    except (ArtifactError, FileNotFoundError, OSError, TypeError, ValueError) as error:
        print(json.dumps({
            "error": str(error),
            "valid_aggregate_report": False,
        }, indent=2, sort_keys=True))
        return 2
    print(json.dumps({
        "code_version": manifest.code_version,
        "config_sha256": manifest.config_sha256,
        "created_at_utc": manifest.created_at_utc,
        "data_version": manifest.data_version,
        "valid_aggregate_report": True,
        "report_sha256": manifest.report_sha256,
        "tables": {
            name: {
                "rows": len(getattr(report, name)),
                "sha256": manifest.table_sha256[name],
            }
            for name in REPORT_TABLES
        },
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
