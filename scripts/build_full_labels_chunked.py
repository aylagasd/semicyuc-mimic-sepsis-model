#!/usr/bin/env python3
"""Build partitioned Sepsis-3 and septic-shock labels."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mimic_sepsis.chunked_labels import ChunkedLabelBuilder
from mimic_sepsis.chunked_sofa import detect_code_version


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_dir", type=Path)
    parser.add_argument("sofa_run", type=Path)
    parser.add_argument("--output-root", type=Path, default=Path("data/derived/full_labels"))
    parser.add_argument("--rules", type=Path, default=Path("config/antimicrobial_rules.csv"))
    parser.add_argument("--shock-config", type=Path, default=Path("config/septic_shock.json"))
    parser.add_argument("--duckdb-memory-limit", default="8GB")
    parser.add_argument("--duckdb-temp-dir", type=Path)
    parser.add_argument("--duckdb-threads", type=int, default=2)
    parser.add_argument("--code-version")
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    code_version = args.code_version or detect_code_version(
        Path(__file__).resolve().parents[1]
    )
    result = ChunkedLabelBuilder(
        args.source_dir, args.sofa_run, args.output_root,
        rules_path=args.rules, shock_config_path=args.shock_config,
        code_version=code_version,
        duckdb_memory_limit=args.duckdb_memory_limit,
        duckdb_temp_dir=args.duckdb_temp_dir,
        duckdb_threads=args.duckdb_threads,
    ).run(resume=args.resume)
    print(json.dumps({
        name: {"parts": len(item.parts), "rows": item.rows}
        for name, item in result.items()
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
