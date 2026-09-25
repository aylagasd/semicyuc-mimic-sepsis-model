#!/usr/bin/env python3
"""Build partitioned leakage-safe feature matrices from reduced MIMIC-IV."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mimic_sepsis.chunked_features import ChunkedFeatureBuilder
from mimic_sepsis.chunked_landmarks import PARTITIONS
from mimic_sepsis.chunked_sofa import detect_code_version


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_dir", type=Path)
    parser.add_argument("landmark_run", type=Path)
    parser.add_argument("--output-root", type=Path, default=Path("data/derived/full_features"))
    parser.add_argument("--feature-config", type=Path, default=Path("config/features.json"))
    parser.add_argument("--duckdb-memory-limit", default="8GB")
    parser.add_argument("--duckdb-temp-dir", type=Path)
    parser.add_argument("--code-version")
    parser.add_argument(
        "--partitions", nargs="+", choices=PARTITIONS,
        default=list(PARTITIONS),
    )
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = ChunkedFeatureBuilder(
        args.source_dir, args.landmark_run, args.output_root,
        feature_config_path=args.feature_config,
        code_version=args.code_version or detect_code_version(
            Path(__file__).resolve().parents[1]
        ),
        partitions=tuple(args.partitions),
        duckdb_memory_limit=args.duckdb_memory_limit,
        duckdb_temp_dir=args.duckdb_temp_dir,
    ).run(resume=args.resume)
    print(json.dumps({
        name: {"parts": len(item.parts), "rows": item.rows}
        for name, item in result.items()
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
