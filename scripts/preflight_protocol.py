#!/usr/bin/env python3
"""Check whether signed protocol decisions permit a pipeline phase."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mimic_sepsis.deployment import preflight_protocol_status


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("phenotype", "model", "test"))
    parser.add_argument(
        "--config", type=Path, default=Path("config/protocol_status.json")
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    report = preflight_protocol_status(config, args.phase)
    print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    return 0 if report.ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
