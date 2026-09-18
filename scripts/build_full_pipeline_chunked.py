#!/usr/bin/env python3
"""Run the bounded-memory full-MIMIC pipeline after CSV extraction."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mimic_sepsis.chunked_features import ChunkedFeatureBuilder
from mimic_sepsis.chunked_labels import ChunkedLabelBuilder
from mimic_sepsis.chunked_landmarks import ChunkedLandmarkBuilder
from mimic_sepsis.chunked_sofa import ChunkedSofaBuilder, detect_code_version


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_dir", type=Path)
    parser.add_argument("--output-root", type=Path, default=Path("data/derived/full_pipeline"))
    parser.add_argument("--batch-size", type=int, default=250)
    parser.add_argument("--code-version")
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo = Path(__file__).resolve().parents[1]
    code_version = args.code_version or detect_code_version(repo)
    sofa = ChunkedSofaBuilder(
        args.source_dir, args.output_root / "sofa",
        batch_size=args.batch_size, code_version=code_version,
    ).run(resume=args.resume)
    sofa_run = args.output_root / "sofa" / sofa.config_sha256[:16]
    labels = ChunkedLabelBuilder(
        args.source_dir, sofa_run, args.output_root / "labels",
        rules_path=repo / "config" / "antimicrobial_rules.csv",
        shock_config_path=repo / "config" / "septic_shock.json",
        code_version=code_version,
    ).run(resume=args.resume)
    label_hash = next(iter(labels.values())).config_sha256
    label_run = args.output_root / "labels" / label_hash[:16]
    landmarks = ChunkedLandmarkBuilder(
        args.source_dir, sofa_run, label_run, args.output_root / "landmarks",
        landmark_config_path=repo / "config" / "landmarks.json",
        split_config_path=repo / "config" / "splits.json",
        code_version=code_version,
    ).run(resume=args.resume)
    landmark_hash = next(iter(landmarks.values())).config_sha256
    landmark_run = args.output_root / "landmarks" / landmark_hash[:16]
    features = ChunkedFeatureBuilder(
        args.source_dir, landmark_run, args.output_root / "features",
        feature_config_path=repo / "config" / "features.json",
        code_version=code_version,
    ).run(resume=args.resume)
    print(json.dumps({
        "sofa": {"run_id": sofa_run.name, "rows": sofa.rows},
        "labels": {name: item.rows for name, item in labels.items()},
        "landmarks": {name: item.rows for name, item in landmarks.items()},
        "features": {name: item.rows for name, item in features.items()},
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
