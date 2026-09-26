#!/usr/bin/env python3
"""Validate aggregate pipeline telemetry against a compute profile."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from mimic_sepsis.resource_validation import audit_pipeline_resources


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("resource_report", type=Path)
    parser.add_argument(
        "--compute-profile", type=Path, default=Path("config/compute_32gb.json")
    )
    return parser.parse_args()


def _load_object(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path.name}")
    return value


def main() -> int:
    args = parse_args()
    try:
        payload = _load_object(args.resource_report)
        profile = _load_object(args.compute_profile)
        audit = audit_pipeline_resources(
            payload,
            profile,
            expected_compute_profile_sha256=hashlib.sha256(
                args.compute_profile.read_bytes()
            ).hexdigest(),
        )
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({
            "error": "resource_report_validation_failed",
            "error_type": type(error).__name__,
            "ready": False,
        }, indent=2))
        return 2
    print(json.dumps(audit.to_dict(), indent=2, sort_keys=True))
    return 0 if audit.ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
