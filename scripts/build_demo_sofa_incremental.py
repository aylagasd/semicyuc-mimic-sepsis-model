#!/usr/bin/env python3
"""Build restartable SOFA and Sepsis-3 artifacts from the MIMIC-IV demo.

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

from mimic_sepsis.antimicrobials import (
    classify_prescriptions,
    confirm_administrations,
    load_antimicrobial_rules,
)
from mimic_sepsis.artifacts import ArtifactStore, ArtifactValidationError
from mimic_sepsis.cohort import StayPolicy, build_adult_icu_cohort
from mimic_sepsis.feature_sources import normalize_lab_feature_events, normalize_vital_events
from mimic_sepsis.features import build_numeric_feature_matrix
from mimic_sepsis.infection import pair_antibiotics_and_cultures
from mimic_sepsis.landmarks import build_multiple_horizons
from mimic_sepsis.sepsis_labels import build_sepsis_episodes, first_sepsis_episode_per_stay
from mimic_sepsis.septic_shock import (
    build_septic_shock_labels,
    normalize_lactate,
    normalize_vasopressor_intervals,
)
from mimic_sepsis.splits import patient_grouped_split
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
COHORT_TABLES = {
    "patients": "hosp/patients.csv.gz",
    "admissions": "hosp/admissions.csv.gz",
}
INFECTION_TABLES = {
    "prescriptions": "hosp/prescriptions.csv.gz",
    "emar": "hosp/emar.csv.gz",
    "microbiologyevents": "hosp/microbiologyevents.csv.gz",
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
        "suspected_infection": {
            "antibiotic_evidence": "first_qualifying_emar_administration",
            "antibiotic_first_hours": 24,
            "culture_first_hours": 72,
            "culture_scope": "blood_only",
        },
        "sepsis3": json.loads(
            (Path(__file__).resolve().parents[1] / "config" / "sepsis3.json")
            .read_text(encoding="utf-8")
        ),
        "septic_shock": json.loads(
            (Path(__file__).resolve().parents[1] / "config" / "septic_shock.json")
            .read_text(encoding="utf-8")
        ),
        "landmarks": json.loads(
            (Path(__file__).resolve().parents[1] / "config" / "landmarks.json")
            .read_text(encoding="utf-8")
        ),
        "splits": json.loads(
            (Path(__file__).resolve().parents[1] / "config" / "splits.json")
            .read_text(encoding="utf-8")
        ),
        "features": json.loads(
            (Path(__file__).resolve().parents[1] / "config" / "features.json")
            .read_text(encoding="utf-8")
        ),
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
        paths = RAW_TABLES | COHORT_TABLES
        if name not in paths:
            raise ValueError(f"Unknown demo table: {name}")
        path = data_dir / paths[name]
        if not path.is_file():
            raise FileNotFoundError(
                f"Missing {path}; run scripts/download_mimic_demo.py first"
            )
        tables[name] = pd.read_csv(path, low_memory=False)
    return tables


def read_infection_tables(data_dir: Path) -> dict[str, pd.DataFrame]:
    """Read the three hospital tables needed by the infection phenotype."""
    tables = {}
    for name, relative in INFECTION_TABLES.items():
        path = data_dir / relative
        if not path.is_file():
            raise FileNotFoundError(f"Missing {path}; run scripts/download_mimic_demo.py first")
        tables[name] = pd.read_csv(path, low_memory=False)
    return tables


def build_cohort_stage(
    *, data_dir: Path, run_root: Path, config: dict, code_version: str, resume: bool
) -> None:
    store = _store(run_root, "00_cohort")
    names = ("cohort_stays", "cohort_audit", "cohort_flow", "hourly_grid")
    if all(_valid(store, name, config, resume=resume) for name in names):
        return
    tables = read_demo_tables(
        data_dir, ("patients", "admissions", "icustays", "chartevents")
    )
    result = build_adult_icu_cohort(
        tables["patients"], tables["admissions"], tables["icustays"],
        stay_policy=StayPolicy.FIRST_PER_ADMISSION,
    )
    cohort = result.cohort.copy()
    cohort["cohort_included"] = True
    grid = build_icustay_hourly_grid(cohort, tables["chartevents"])
    flow = pd.DataFrame(
        {"metric": list(result.flow), "count": list(result.flow.values())}
    )
    store.write_dataframe(
        "cohort_stays", cohort, data_version=DATA_VERSION,
        code_version=code_version, config=config,
    )
    store.write_dataframe(
        "cohort_audit", result.audit, data_version=DATA_VERSION,
        code_version=code_version, config=config,
    )
    store.write_dataframe(
        "cohort_flow", flow, data_version=DATA_VERSION,
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
    cohort = cohort_store.read_dataframe("cohort_stays", expected_config=config)
    tables = read_demo_tables(data_dir)
    # All downstream SOFA linkage is restricted to the selected study cohort.
    tables["icustays"] = cohort[
        ["subject_id", "hadm_id", "stay_id", "intime", "outtime"]
    ].copy()
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


def build_label_stage(
    *, data_dir: Path, run_root: Path, config: dict, code_version: str, resume: bool
) -> None:
    """Materialize suspected-infection pairs and Sepsis-3 episode labels."""
    label_store = _store(run_root, "40_labels")
    names = (
        "suspected_infection_pairs", "sepsis_episodes", "sepsis_stays",
        "septic_shock_stays",
    )
    if all(_valid(label_store, name, config, resume=resume) for name in names):
        return
    score_store = _store(run_root, "30_score")
    cohort_store = _store(run_root, "00_cohort")
    sofa = score_store.read_dataframe("sofa_hourly", expected_config=config)
    stays = cohort_store.read_dataframe("cohort_stays", expected_config=config)
    sources = read_infection_tables(data_dir)

    repo = Path(__file__).resolve().parents[1]
    rules = load_antimicrobial_rules(repo / "config" / "antimicrobial_rules.csv")
    classified = classify_prescriptions(sources["prescriptions"], rules)
    confirmed = confirm_administrations(classified, sources["emar"])
    antibiotics = confirmed.dropna(subset=["administration_time"])[
        ["subject_id", "hadm_id", "pharmacy_id", "administration_time"]
    ].rename(columns={
        "pharmacy_id": "antibiotic_id", "administration_time": "antibiotic_time"
    })

    microbiology = sources["microbiologyevents"].copy()
    microbiology["culture_time"] = pd.to_datetime(
        microbiology["charttime"], errors="coerce"
    ).fillna(pd.to_datetime(microbiology["chartdate"], errors="coerce"))
    cultures = (
        microbiology.loc[
            microbiology["spec_type_desc"].fillna("").str.contains("BLOOD", case=False)
        ]
        .dropna(subset=["subject_id", "hadm_id", "micro_specimen_id", "culture_time"])
        .sort_values("culture_time")
        .drop_duplicates(["subject_id", "hadm_id", "micro_specimen_id"])
        [["subject_id", "hadm_id", "micro_specimen_id", "culture_time"]]
        .rename(columns={"micro_specimen_id": "culture_id"})
    )
    pairs = pair_antibiotics_and_cultures(antibiotics, cultures)
    episodes = build_sepsis_episodes(pairs, stays, sofa)
    sepsis_stays = first_sepsis_episode_per_stay(episodes)
    shock_sources = read_demo_tables(data_dir, ("labevents", "inputevents"))
    lactates = normalize_lactate(shock_sources["labevents"])
    vasopressors = normalize_vasopressor_intervals(shock_sources["inputevents"])
    shock_config = config["septic_shock"]
    shock_stays = build_septic_shock_labels(
        sepsis_stays, lactates, vasopressors,
        lactate_threshold=shock_config["lactate_threshold_mmol_l"],
        concurrency_hours=shock_config["concurrency_hours"],
        association_hours=shock_config["sepsis_association_hours_after"],
    )
    frames = (pairs, episodes, sepsis_stays, shock_stays)
    for name, frame in zip(names, frames, strict=True):
        label_store.write_dataframe(
            name, frame, data_version=DATA_VERSION,
            code_version=code_version, config=config,
        )


def build_landmark_stage(
    *, run_root: Path, config: dict, code_version: str, resume: bool
) -> None:
    """Materialize long-format risk sets for both prediction targets."""
    store = _store(run_root, "50_landmarks")
    names = tuple(
        f"{target}_{partition}_landmarks"
        for target in ("sepsis3", "septic_shock")
        for partition in ("development", "validation", "test")
    )
    if all(_valid(store, name, config, resume=resume) for name in names):
        return
    cohort = _store(run_root, "00_cohort").read_dataframe(
        "cohort_stays", expected_config=config
    )
    labels = _store(run_root, "40_labels")
    sepsis = labels.read_dataframe("sepsis_stays", expected_config=config)
    shock = labels.read_dataframe("septic_shock_stays", expected_config=config)
    landmark_config = config["landmarks"]
    common = {
        "horizons_hours": tuple(landmark_config["horizons_hours"]),
        "minimum_observation_hours": landmark_config["minimum_observation_hours"],
        "landmark_interval_hours": landmark_config["landmark_interval_hours"],
    }
    sepsis_landmarks = build_multiple_horizons(
        cohort, sepsis, event_time_column="t0", **common
    )
    sepsis_landmarks["target"] = "sepsis3"
    shock_landmarks = build_multiple_horizons(
        cohort, shock, event_time_column="shock_t0", **common
    )
    shock_landmarks["target"] = "septic_shock"
    split_config = config["splits"]
    patient_map = patient_grouped_split(
        cohort[["subject_id"]].drop_duplicates(),
        proportions=split_config["proportions"], seed=split_config["seed"],
    ).set_index("subject_id")["partition"]
    for frame in (sepsis_landmarks, shock_landmarks):
        frame["partition"] = frame["subject_id"].map(patient_map).astype("string")
    frames = {"sepsis3": sepsis_landmarks, "septic_shock": shock_landmarks}
    for target, frame in frames.items():
        for partition in ("development", "validation", "test"):
            store.write_dataframe(
                f"{target}_{partition}_landmarks",
                frame.loc[frame["partition"].eq(partition)].reset_index(drop=True),
                data_version=DATA_VERSION, code_version=code_version, config=config,
            )


def build_feature_stage(
    *, data_dir: Path, run_root: Path, config: dict, code_version: str, resume: bool
) -> None:
    """Materialize predictor-only matrices, physically separated by partition."""
    store = _store(run_root, "60_features")
    names = tuple(
        f"{target}_{partition}_features"
        for target in ("sepsis3", "septic_shock")
        for partition in ("development", "validation", "test")
    )
    if all(_valid(store, name, config, resume=resume) for name in names):
        return
    cohort = _store(run_root, "00_cohort").read_dataframe(
        "cohort_stays", expected_config=config
    )
    raw = read_demo_tables(data_dir, ("chartevents", "labevents"))
    events = pd.concat(
        [normalize_vital_events(raw["chartevents"]),
         normalize_lab_feature_events(raw["labevents"], cohort)],
        ignore_index=True,
    )
    feature_config = config["features"]
    landmark_store = _store(run_root, "50_landmarks")
    for target in ("sepsis3", "septic_shock"):
        for partition in ("development", "validation", "test"):
            stem = f"{target}_{partition}"
            landmarks = landmark_store.read_dataframe(
                f"{stem}_landmarks", expected_config=config
            )[["subject_id", "hadm_id", "stay_id", "landmark_time"]]
            matrix = build_numeric_feature_matrix(
                landmarks, events,
                variables=tuple(feature_config["variables"]),
                lookbacks_hours=tuple(feature_config["lookbacks_hours"]),
            )
            store.write_dataframe(
                f"{stem}_features", matrix, data_version=DATA_VERSION,
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
        "--stage", choices=("cohort", "score", "label", "landmark", "feature", "all"), default="all",
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
    if args.stage in {"label", "all"}:
        if args.stage == "label":
            build_cohort_stage(
                data_dir=args.data_dir, run_root=run_root, config=config,
                code_version=code_version, resume=True,
            )
            build_score_stage(
                data_dir=args.data_dir, run_root=run_root, config=config,
                code_version=code_version, resume=True,
            )
        build_label_stage(
            data_dir=args.data_dir, run_root=run_root, config=config,
            code_version=code_version, resume=args.resume,
        )
    if args.stage in {"landmark", "all"}:
        if args.stage == "landmark":
            build_cohort_stage(
                data_dir=args.data_dir, run_root=run_root, config=config,
                code_version=code_version, resume=True,
            )
            build_score_stage(
                data_dir=args.data_dir, run_root=run_root, config=config,
                code_version=code_version, resume=True,
            )
            build_label_stage(
                data_dir=args.data_dir, run_root=run_root, config=config,
                code_version=code_version, resume=True,
            )
        build_landmark_stage(
            run_root=run_root, config=config,
            code_version=code_version, resume=args.resume,
        )
    if args.stage in {"feature", "all"}:
        if args.stage == "feature":
            build_cohort_stage(
                data_dir=args.data_dir, run_root=run_root, config=config,
                code_version=code_version, resume=True,
            )
            build_score_stage(
                data_dir=args.data_dir, run_root=run_root, config=config,
                code_version=code_version, resume=True,
            )
            build_label_stage(
                data_dir=args.data_dir, run_root=run_root, config=config,
                code_version=code_version, resume=True,
            )
            build_landmark_stage(
                run_root=run_root, config=config, code_version=code_version, resume=True,
            )
        build_feature_stage(
            data_dir=args.data_dir, run_root=run_root, config=config,
            code_version=code_version, resume=args.resume,
        )
    print(run_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
