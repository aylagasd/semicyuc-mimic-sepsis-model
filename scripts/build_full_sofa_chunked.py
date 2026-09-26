#!/usr/bin/env python3
"""Build partitioned hourly SOFA from the reduced full-MIMIC extract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mimic_sepsis.chunked_sofa import ChunkedSofaBuilder, detect_code_version


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_dir", type=Path)
    parser.add_argument("--output-root", type=Path, default=Path("data/derived/full_sofa"))
    parser.add_argument("--batch-size", type=int, default=250)
    parser.add_argument("--duckdb-memory-limit", default="8GB")
    parser.add_argument("--duckdb-temp-dir", type=Path)
    parser.add_argument("--duckdb-threads", type=int, default=2)
    parser.add_argument("--code-version")
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = ChunkedSofaBuilder(
        args.source_dir,
        args.output_root,
        batch_size=args.batch_size,
        code_version=args.code_version or detect_code_version(Path(__file__).resolve().parents[1]),
        duckdb_memory_limit=args.duckdb_memory_limit,
        duckdb_temp_dir=args.duckdb_temp_dir,
        duckdb_threads=args.duckdb_threads,
    ).run(resume=args.resume)
    print(json.dumps({
        "artifact": result.artifact,
        "config_sha256": result.config_sha256,
        "parts": len(result.parts),
        "rows": result.rows,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
