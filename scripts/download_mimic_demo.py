#!/usr/bin/env python3
"""Download the official public MIMIC-IV Demo v2.2 with checksum validation."""

from __future__ import annotations

import argparse
from pathlib import Path

from mimic_sepsis.demo import DEMO_VERSION, download_demo


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--destination",
        type=Path,
        default=Path("data") / "mimic-iv-demo" / DEMO_VERSION,
    )
    parser.add_argument("--force", action="store_true", help="Download files again")
    args = parser.parse_args()
    files = download_demo(args.destination, force=args.force)
    total_bytes = sum(path.stat().st_size for path in files)
    print(f"Verified {len(files)} files ({total_bytes / 1024 / 1024:.1f} MiB)")
    print(args.destination.resolve())


if __name__ == "__main__":
    main()
