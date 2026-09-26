#!/usr/bin/env python3
"""Emit the static, identifier-free D004 antimicrobial review packet."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mimic_sepsis.antimicrobials import audit_antimicrobial_rules


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rules",
        type=Path,
        default=Path("config/antimicrobial_rules.csv"),
        help="Ordered antimicrobial rule CSV.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional JSON destination; stdout is used when omitted.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = audit_antimicrobial_rules(args.rules)
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(payload, end="")
        return
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(args.output)
    print(json.dumps({"output": str(args.output), "rules_sha256": report["rules_sha256"]}))


if __name__ == "__main__":
    main()
