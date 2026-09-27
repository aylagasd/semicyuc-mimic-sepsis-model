#!/usr/bin/env python3
"""Execute an inclusive range of the canonical notebooks from clean kernels."""

from __future__ import annotations

import argparse
from pathlib import Path

from mimic_sepsis.notebook_runner import discover_notebooks, execute_notebooks


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--end", type=int, default=13)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument(
        "--output-dir", type=Path,
        default=Path("data/derived/notebook_runs"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    notebooks = discover_notebooks(
        root / "notebooks", start=args.start, end=args.end
    )
    execute_notebooks(
        notebooks,
        project_root=root,
        output_dir=args.output_dir,
        timeout_seconds=args.timeout,
    )
    print(f"Completed notebooks {args.start:02d}-{args.end:02d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
