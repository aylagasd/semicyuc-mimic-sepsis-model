#!/usr/bin/env python3
"""Report aggregate development information without opening locked test data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mimic_sepsis.information_audit import audit_development_information


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("development_landmarks", type=Path)
    parser.add_argument("development_features", type=Path)
    parser.add_argument("--model-config", type=Path, default=Path("config/modeling.json"))
    parser.add_argument("--sample-size-config", type=Path, default=Path("config/sample_size.json"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    model = json.loads(args.model_config.read_text(encoding="utf-8"))
    planning = json.loads(args.sample_size_config.read_text(encoding="utf-8"))
    result = audit_development_information(
        args.development_landmarks,
        args.development_features,
        target=planning["primary_target"],
        horizon_hours=planning["primary_horizon_hours"],
        baseline_features=model["clinical_baseline_features"],
        anticipated_cox_snell_r2=planning["anticipated_cox_snell_r2"],
    )
    print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
