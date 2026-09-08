#!/usr/bin/env python3
"""Build restartable SOFA artifacts from the local MIMIC-IV demo.

The CLI deliberately never accepts credentials: its input is an already
downloaded MIMIC-IV demo directory.  Patient-level outputs belong below
``data/derived`` and must not be committed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Iterable

import pandas as pd

from mimic_sepsis.artifacts import ArtifactStore, ArtifactValidationError
from mimic_sepsis.sofa_demo import build_demo_hourly_sofa
from mimic_sepsis.sofa_hourly import build_icustay_hourly_grid


DATA_VERSION = "2.2"
MIMIC_CODE_VERSION = "v2.4.0"
MIMIC_CODE_COMMIT = "570ef01"
SCHEMA_VERSION = 1
RAW_TABLES = {
    "icustays": "icu/icustays.csv.gz",
    "chartevents": "icu/chartevents.csv.gz",
    "inputevents": "icu/inputevents.csv.gz",
    "outputevents": "icu/outputevents.csv.gz",
    "procedureevents": "icu/procedureevents.csv.gz",
    "labevents": "hosp/labevents.csv.gz",
}
COMPONENTS = (
    "respiratory",
    "coagulation",
    "liver",
    "cardiovascular",
    "cns",
    "renal",
)


def canonical_config() -> dict:
    """Return the credential-free effective configuration."""
    return {
        "artifact_schema_version": SCHEMA_VERSION,
        "backend": "demo-files",
        "data_release": DATA_VERSION,
        "dialect": "pandas",
        "gcs_contemporaneous_minutes": 0,
        "mimic_code_commit": MIMIC_CODE_COMMIT,
        "mimic_code_version": MIMIC_CODE_VERSION,
        "rolling_window_hours": 24,
        "window_semantics": "(endtime-24h,endtime]",
    }


def config_hash(config: dict) -> str:
    payload = json.dumps(
        config, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def make_run_id(config: dict) -> str:
    return (
        f"demo-{config['data_release']}-{config['mimic_code_version']}-"
        f"{config_hash(config)[:12]}"
    )


def project_version(repo: Path) -> str:
    """Return a useful code identity without failing outside a Git checkout."""
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        return commit + ("-DIRTY" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _store(run_root: Path, directory: str) -> ArtifactStore:
    return ArtifactStore(run_root / directory)


def _valid(
    store: ArtifactStore, name: str, config: dict, *, resume: bool
) -> bool:
    if not resume:
        return False
    try:
        store.validate(name, expected_config=config)
        return True
    except (FileNotFoundError, ArtifactValidationError):
        return False


def read_demo_tables(data_dir: Path, names: Iterable[str] = RAW_TABLES) -> dict[str, pd.DataFrame]:
    tables: dict[str, pd.DataFrame] = {}
    for name in names:
        path = data_dir / RAW_TABLES[name]
        if not path.is_file():
            raise FileNotFoundError(
                f"Missing {path}; run scripts/download_mimic_demo.py first"
            )
        tables[name] = pd.read_csv(path, low_memory=False)
    return tables


def build_cohort_stage(
    *, data_dir: Path, run_root: Path, config: dict, code_version: str, resume: bool
) -> None:
    store = _store(run_root, "00_cohort")
    if _valid(store, "cohort_stays", config, resume=resume) and _valid(
        store, "hourly_grid", config, resume=resume
    ):
        return
    tables = read_demo_tables(data_dir, ("icustays", "chartevents"))
    stays = tables["icustays"].copy()
    cohort = stays[
        ["subject_id", "hadm_id", "stay_id", "intime", "outtime"]
    ].copy()
    cohort["cohort_included"] = True
    cohort["exclusion_reason"] = pd.Series(pd.NA, index=cohort.index, dtype="string")
    grid = build_icustay_hourly_grid(stays, tables["chartevents"])
    store.write_dataframe(
        "cohort_stays", cohort, data_version=DATA_VERSION,
        code_version=code_version, config=config,
    )
    store.write_dataframe(
        "hourly_grid", grid, data_version=DATA_VERSION,
        code_version=code_version, config=config,
    )


def build_score_stage(
    *, data_dir: Path, run_root: Path, config: dict, code_version: str, resume: bool
) -> None:
    score_store = _store(run_root, "30_score")
    if _valid(score_store, "sofa_hourly", config, resume=resume):
        return
    cohort_store = _store(run_root, "00_cohort")
    cohort_store.validate("hourly_grid", expected_config=config)
    tables = read_demo_tables(data_dir)
    result = build_demo_hourly_sofa(**tables)

    component_store = _store(run_root, "20_components")
    keys = ["stay_id", "hr", "endtime"]
    for component in COMPONENTS:
        score = f"sofa_{component}"
        frame = result[keys + [score]].rename(columns={score: "score_24h"})
        frame["observed_24h"] = frame["score_24h"].notna()
        # The monolithic demo implementation does not expose event cardinality.
        # Nullable Int32 makes that limitation explicit rather than inventing it.
        frame["source_event_count_24h"] = pd.array(
            [pd.NA] * len(frame), dtype="Int32"
        )
        component_store.write_dataframe(
            f"{component}_hourly", frame, data_version=DATA_VERSION,
            code_version=code_version, config=config,
        )
    score_store.write_dataframe(
        "sofa_hourly", result, data_version=DATA_VERSION,
        code_version=code_version, config=config,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir", type=Path, default=Path("data/mimic-iv-demo/2.2"),
        help="directory containing hosp/ and icu/ from MIMIC-IV Demo 2.2",
    )
    parser.add_argument(
        "--output-root", type=Path, default=Path("data/derived/sofa"),
        help="protected root for derived SOFA runs",
    )
    parser.add_argument(
        "--stage", choices=("cohort", "score", "all"), default="all",
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="reuse only artifacts whose checksum and configuration validate",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = canonical_config()
    run_id = make_run_id(config)
    run_root = args.output_root / run_id
    code_version = project_version(Path(__file__).resolve().parents[1])
    if args.stage in {"cohort", "all"}:
        build_cohort_stage(
            data_dir=args.data_dir, run_root=run_root, config=config,
            code_version=code_version, resume=args.resume,
        )
    if args.stage in {"score", "all"}:
        if args.stage == "score":
            # Score is dependent on a valid grid and remains convenient alone.
            build_cohort_stage(
                data_dir=args.data_dir, run_root=run_root, config=config,
                code_version=code_version, resume=True,
            )
        build_score_stage(
            data_dir=args.data_dir, run_root=run_root, config=config,
            code_version=code_version, resume=args.resume,
        )
    print(run_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
