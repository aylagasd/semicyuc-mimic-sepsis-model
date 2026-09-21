#!/usr/bin/env python3
"""Verify row-multiset equivalence of demo and chunked pipeline artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mimic_sepsis.artifacts import ArtifactStore
from mimic_sepsis.chunked_labels import LABEL_ARTIFACTS
from mimic_sepsis.chunked_landmarks import PARTITIONS, TARGETS
from mimic_sepsis.chunked_sofa import validate_partitioned_dataset
from mimic_sepsis.equivalence import compare_parquet


COHORT_AUDIT_COLUMNS = (
    "subject_id", "hadm_id", "stay_id", "intime", "outtime", "age_at_icu",
    "first_careunit", "gender", "admission_type", "admission_location",
    "insurance", "race",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("canonical_run", type=Path)
    parser.add_argument("sofa_run", type=Path)
    parser.add_argument("label_run", type=Path)
    parser.add_argument("landmark_run", type=Path)
    parser.add_argument("feature_run", type=Path)
    parser.add_argument(
        "--full-extract-root", type=Path,
        help="Optionally compare common cohort/audit columns from the CSV extractor.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    canonical_sofa = ArtifactStore(args.canonical_run / "30_score")
    if canonical_sofa.read_manifest("sofa_hourly").data_version != "2.2":
        raise ValueError("This verifier is restricted to MIMIC-IV Demo 2.2")
    comparisons = [
        ("sofa_hourly", args.sofa_run, args.canonical_run / "30_score")
    ]
    comparisons.extend(
        (name, args.label_run / name, args.canonical_run / "40_labels")
        for name in LABEL_ARTIFACTS
    )
    for target in TARGETS:
        for partition in PARTITIONS:
            landmark = f"{target}_{partition}_landmarks"
            feature = f"{target}_{partition}_features"
            comparisons.append((
                landmark, args.landmark_run / landmark,
                args.canonical_run / "50_landmarks",
            ))
            comparisons.append((
                feature, args.feature_run / feature,
                args.canonical_run / "60_features",
            ))
    report = {}
    success = True
    for name, chunk_root, canonical_store in comparisons:
        validate_partitioned_dataset(chunk_root, name)
        canonical_manifest = ArtifactStore(canonical_store).read_manifest(name)
        if canonical_manifest.data_version != "2.2":
            raise ValueError("All canonical artifacts must be MIMIC-IV Demo 2.2")
        result = compare_parquet(
            chunk_root / "parts" / "part-*.parquet",
            canonical_store / f"{name}.parquet",
        )
        report[name] = {
            "equivalent": result.equivalent,
            "left_only": result.left_only,
            "right_only": result.right_only,
            "rows": result.left_rows,
        }
        success &= result.equivalent
    if args.full_extract_root is not None:
        extract_manifest = json.loads(
            (args.full_extract_root / "cohort_stays.manifest.json").read_text(
                encoding="utf-8"
            )
        )
        if extract_manifest.get("data_version") != "2.2":
            raise ValueError("The full-extract cohort must be MIMIC-IV Demo 2.2")
        cohort_result = compare_parquet(
            args.full_extract_root / "cohort_stays.parquet",
            args.canonical_run / "00_cohort" / "cohort_stays.parquet",
            columns=COHORT_AUDIT_COLUMNS,
        )
        report["cohort_stays_audit_columns"] = {
            "equivalent": cohort_result.equivalent,
            "left_only": cohort_result.left_only,
            "right_only": cohort_result.right_only,
            "rows": cohort_result.left_rows,
        }
        success &= cohort_result.equivalent
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
