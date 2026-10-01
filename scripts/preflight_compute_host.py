#!/usr/bin/env python3
"""Check host RAM, CPU, and disks before the full MIMIC-IV workflow."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mimic_sepsis.host_preflight import inspect_compute_host


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-path", type=Path, required=True)
    parser.add_argument("--temp-path", type=Path, required=True)
    parser.add_argument(
        "--compute-profile", type=Path, default=Path("config/compute_32gb.json")
    )
    parser.add_argument("--minimum-work-free-gb", type=float, default=0)
    parser.add_argument("--minimum-temp-free-gb", type=float, default=0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        profile = json.loads(args.compute_profile.read_text(encoding="utf-8"))
        report = inspect_compute_host(
            profile,
            work_path=args.work_path,
            temp_path=args.temp_path,
            minimum_work_free_gib=args.minimum_work_free_gb,
            minimum_temp_free_gib=args.minimum_temp_free_gb,
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({
            "error": "host_preflight_failed",
            "error_type": type(error).__name__,
            "ready": False,
        }, indent=2, sort_keys=True))
        return 2
    print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    return 0 if report.ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
