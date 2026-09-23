#!/usr/bin/env python3
"""Build partitioned future-outcome landmarks from chunked labels."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mimic_sepsis.chunked_landmarks import ChunkedLandmarkBuilder, PARTITIONS
from mimic_sepsis.chunked_sofa import detect_code_version


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_dir", type=Path)
    parser.add_argument("sofa_run", type=Path)
    parser.add_argument("label_run", type=Path)
    parser.add_argument("--output-root", type=Path, default=Path("data/derived/full_landmarks"))
    parser.add_argument("--landmark-config", type=Path, default=Path("config/landmarks.json"))
    parser.add_argument("--split-config", type=Path, default=Path("config/splits.json"))
    parser.add_argument("--code-version")
    parser.add_argument(
        "--partitions", nargs="+", choices=PARTITIONS,
        default=list(PARTITIONS),
    )
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = ChunkedLandmarkBuilder(
        args.source_dir, args.sofa_run, args.label_run, args.output_root,
        landmark_config_path=args.landmark_config,
        split_config_path=args.split_config,
        code_version=args.code_version or detect_code_version(
            Path(__file__).resolve().parents[1]
        ),
        partitions=tuple(args.partitions),
    ).run(resume=args.resume)
    print(json.dumps({
        name: {"parts": len(item.parts), "rows": item.rows}
        for name, item in result.items()
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
