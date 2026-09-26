#!/usr/bin/env python3
"""Out-of-core extraction from an authorized MIMIC-IV CSV distribution."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mimic_sepsis.deployment import preflight_mimic_files
from mimic_sepsis.cohort import StayPolicy
from mimic_sepsis.full_extract import FullCSVExtractor


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_dir", type=Path)
    parser.add_argument("--data-version", required=True)
    parser.add_argument("--minimum-age", type=int, default=18)
    parser.add_argument(
        "--stay-policy",
        choices=tuple(policy.value for policy in StayPolicy),
        default=StayPolicy.FIRST_PER_ADMISSION.value,
    )
    parser.add_argument("--output-dir", type=Path, default=Path("data/derived/full_extract"))
    parser.add_argument("--temp-dir", type=Path)
    parser.add_argument("--memory-limit", default="4GB")
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    preflight = preflight_mimic_files(args.data_dir)
    if not preflight.ready:
        print(json.dumps(preflight.to_dict(), indent=2, sort_keys=True))
        return 2
    extractor = FullCSVExtractor(
        args.data_dir, args.output_dir, data_version=args.data_version,
        minimum_age=args.minimum_age, stay_policy=args.stay_policy,
        memory_limit=args.memory_limit, temp_dir=args.temp_dir,
        threads=args.threads,
    )
    manifests = extractor.run(resume=args.resume)
    print(json.dumps([
        {"artifact": item.artifact, "rows": item.rows, "sha256": item.sha256}
        for item in manifests
    ], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
