#!/usr/bin/env python3
"""Validate a downloaded MIMIC-IV tree without reading patient rows."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mimic_sepsis.deployment import preflight_mimic_files


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_dir", type=Path)
    parser.add_argument("--minimum-free-gb", type=float, default=0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = preflight_mimic_files(
        args.data_dir, minimum_free_gb=args.minimum_free_gb
    )
    print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    return 0 if report.ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
