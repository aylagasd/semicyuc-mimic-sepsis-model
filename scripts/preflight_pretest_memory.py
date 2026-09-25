#!/usr/bin/env python3
"""Estimate pre-test working memory after safe column/horizon projection."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mimic_sepsis.pretest_inputs import load_partitioned_pretest_config
from mimic_sepsis.resource_planning import audit_pretest_memory


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_config", type=Path)
    parser.add_argument(
        "--model-config", type=Path, default=Path("config/modeling.json")
    )
    parser.add_argument(
        "--compute-profile", type=Path, default=Path("config/compute_32gb.json")
    )
    return parser.parse_args()


def _load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def main() -> int:
    args = parse_args()
    try:
        model = _load_json(args.model_config)
        profile = _load_json(args.compute_profile)
        if profile.get("schema_version") != 1:
            raise ValueError("Unsupported compute profile")
        bundle = load_partitioned_pretest_config(
            args.source_config,
            feature_columns=model["clinical_baseline_features"],
            horizon_hours=int(model["primary_horizon_hours"]),
        )
        audit = audit_pretest_memory(
            bundle,
            target_ram_gib=float(profile["target_ram_gib"]),
            maximum_ram_fraction=float(profile["maximum_ram_fraction"]),
            working_set_multiplier=float(profile["working_set_multiplier"]),
            fixed_overhead_gib=float(profile["fixed_overhead_gib"]),
        )
    except (KeyError, OSError, TypeError, ValueError) as error:
        print(json.dumps({"error": str(error), "ready_for_target": False}, indent=2))
        return 2
    result = audit.to_dict()
    result.update({
        "data_version": bundle.data_version,
        "feature_count": len(model["clinical_baseline_features"]),
        "horizon_hours": int(model["primary_horizon_hours"]),
        "source_run_id": bundle.source_run_id,
    })
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if audit.ready_for_target else 2


if __name__ == "__main__":
    raise SystemExit(main())
