"""Protected aggregate evidence for the repeated-ICU-stay policy (D002)."""

from __future__ import annotations

from pathlib import Path
import tempfile
from typing import Any, Mapping, Sequence

import duckdb
import pandas as pd

from .cohort import StayPolicy, build_adult_icu_cohort
from .artifacts import ArtifactStore
from .demo import file_sha256
from .duckdb_runtime import configure_duckdb, validate_duckdb_runtime
from .full_extract import _sql_path


COHORT_SOURCE_FILES = {
    "patients": "hosp/patients.csv.gz",
    "admissions": "hosp/admissions.csv.gz",
    "icustays": "icu/icustays.csv.gz",
}
COHORT_SOURCE_COLUMNS = {
    "patients": ("subject_id", "anchor_age", "anchor_year"),
    "admissions": ("subject_id", "hadm_id"),
    "icustays": ("subject_id", "hadm_id", "stay_id", "intime", "outtime"),
}

POLICY_PIPELINE_ARTIFACTS = {
    "00_cohort": ("cohort_stays",),
    "30_score": ("sofa_hourly",),
    "40_labels": (
        "suspected_infection_pairs", "sepsis_stays", "septic_shock_stays",
    ),
    "50_landmarks": tuple(
        f"{target}_{partition}_landmarks"
        for target in ("sepsis3", "septic_shock")
        for partition in ("development", "validation", "test")
    ),
    "60_features": tuple(
        f"{target}_{partition}_features"
        for target in ("sepsis3", "septic_shock")
        for partition in ("development", "validation", "test")
    ),
}


def load_cohort_sources(
    data_dir: str | Path,
    *,
    memory_limit: str = "1GB",
    temp_dir: str | Path | None = None,
    threads: int = 2,
) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    """Read only columns needed by D002 and hash the three source files."""
    root = Path(data_dir)
    memory_limit, threads = validate_duckdb_runtime(memory_limit, threads)
    paths = {
        name: root / relative for name, relative in COHORT_SOURCE_FILES.items()
    }
    missing = [name for name, path in paths.items() if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "Missing cohort source files: " + ", ".join(sorted(missing))
        )
    connection = duckdb.connect()
    try:
        configure_duckdb(
            connection,
            memory_limit=memory_limit,
            temp_directory=Path(
                temp_dir
                or Path(tempfile.gettempdir()) / "mimic_sepsis_cohort_audit_duckdb"
            ),
            threads=threads,
        )
        frames = {}
        for name, path in paths.items():
            columns = ", ".join(COHORT_SOURCE_COLUMNS[name])
            frames[name] = connection.execute(
                f"SELECT {columns} FROM read_csv_auto("
                f"'{_sql_path(path)}', header=true)"
            ).fetchdf()
    finally:
        connection.close()
    hashes = {name: file_sha256(path) for name, path in paths.items()}
    return frames, hashes


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    forbidden = {"subject_id", "hadm_id", "stay_id"} & set(frame.columns)
    if forbidden:
        raise ValueError(
            "Cohort evidence contains row identifiers: "
            + ", ".join(sorted(forbidden))
        )
    return frame.astype(object).where(pd.notna(frame), None).to_dict("records")


def build_cohort_policy_evidence(
    patients: pd.DataFrame,
    admissions: pd.DataFrame,
    icustays: pd.DataFrame,
    *,
    data_version: str,
    source_sha256: Mapping[str, str],
    protocol_status: Mapping[str, str],
    policies: Sequence[str],
    minimum_age: int = 18,
) -> dict[str, Any]:
    """Rebuild all prespecified cohorts and return identifier-free evidence."""
    requested = [StayPolicy(value) for value in policies]
    expected = [
        StayPolicy.FIRST_PER_ADMISSION,
        StayPolicy.FIRST_PER_PATIENT,
        StayPolicy.ALL,
    ]
    if requested != expected:
        raise ValueError(
            "Cohort policies must be predeclared in primary/patient/all order"
        )
    if protocol_status.get("D002") is None:
        raise ValueError("Protocol status is missing D002")

    results = {
        policy: build_adult_icu_cohort(
            patients, admissions, icustays,
            minimum_age=minimum_age, stay_policy=policy,
        )
        for policy in requested
    }
    first_admission = set(
        results[StayPolicy.FIRST_PER_ADMISSION].cohort["stay_id"]
    )
    first_patient = set(results[StayPolicy.FIRST_PER_PATIENT].cohort["stay_id"])
    all_stays = set(results[StayPolicy.ALL].cohort["stay_id"])
    if not first_patient <= first_admission <= all_stays:
        raise ValueError("Cohort policy selections violate the required nesting")

    flow = pd.DataFrame([
        {"policy": policy.value, **results[policy].flow}
        for policy in requested
    ])
    primary_count = results[StayPolicy.FIRST_PER_ADMISSION].flow[
        "selected_icu_stays"
    ]
    comparison_rows = []
    for policy in requested:
        selected = set(results[policy].cohort["stay_id"])
        comparison_rows.append({
            "policy": policy.value,
            "selected_icu_stays": len(selected),
            "added_vs_primary": len(selected - first_admission),
            "removed_vs_primary": len(first_admission - selected),
            "percent_of_primary_stays": (
                100 * len(selected) / primary_count if primary_count else None
            ),
        })
    comparison = pd.DataFrame(comparison_rows)

    exclusion_rows = []
    for policy in requested:
        counts = (
            results[policy].audit["exclusion_reason"]
            .fillna("selected")
            .value_counts(dropna=False)
        )
        for reason, count in counts.items():
            exclusion_rows.append({
                "policy": policy.value,
                "disposition": str(reason),
                "icu_stays": int(count),
            })
    exclusions = pd.DataFrame(exclusion_rows).sort_values(
        ["policy", "disposition"]
    ).reset_index(drop=True)

    return {
        "schema_version": 1,
        "purpose": "D002_protocol_freeze_review_only",
        "distribution_class": "protected_aggregate_unsuppressed_counts",
        "clinical_status_mutated": False,
        "source": {
            "data_version": str(data_version),
            "sha256": dict(source_sha256),
        },
        "configuration": {
            "minimum_age": int(minimum_age),
            "policies": [policy.value for policy in requested],
        },
        "tables": {
            "cohort_flow": _records(flow),
            "policy_comparison": _records(comparison),
            "exclusion_disposition": _records(exclusions),
            "decision_evidence": [{
                "decision_id": "D002",
                "current_status": protocol_status["D002"],
                "evidence_in_report": "comparative_cohort_flow",
                "remaining_requirement": (
                    "clinical/methodological sign-off; downstream phenotype and "
                    "model sensitivities require separate full-pipeline runs"
                ),
            }],
        },
    }


def build_demo_policy_outcome_evidence(
    run_roots: Mapping[str, str | Path],
    *,
    expected_configs: Mapping[str, Mapping[str, Any]],
    protocol_status: Mapping[str, str],
) -> dict[str, Any]:
    """Validate full demo runs and compare D002 downstream counts safely."""
    policies = [
        StayPolicy.FIRST_PER_ADMISSION.value,
        StayPolicy.FIRST_PER_PATIENT.value,
        StayPolicy.ALL.value,
    ]
    if list(run_roots) != policies or list(expected_configs) != policies:
        raise ValueError("Policy runs must use primary/patient/all order")
    if protocol_status.get("D002") is None:
        raise ValueError("Protocol status is missing D002")

    rows = []
    provenance = {}
    cohort_ids: dict[str, set[Any]] = {}
    for policy in policies:
        root = Path(run_roots[policy])
        config = expected_configs[policy]
        manifests = {}
        for directory, names in POLICY_PIPELINE_ARTIFACTS.items():
            store = ArtifactStore(root / directory)
            for name in names:
                manifests[name] = store.validate(
                    name, expected_config=config
                )
        config_hashes = {item.config_sha256 for item in manifests.values()}
        code_versions = {item.code_version for item in manifests.values()}
        if len(config_hashes) != 1 or len(code_versions) != 1:
            raise ValueError(
                f"Pipeline provenance is inconsistent for policy {policy}"
            )

        cohort = ArtifactStore(root / "00_cohort").read_dataframe(
            "cohort_stays", expected_config=config
        )
        pairs = ArtifactStore(root / "40_labels").read_dataframe(
            "suspected_infection_pairs", expected_config=config
        )
        sepsis = ArtifactStore(root / "40_labels").read_dataframe(
            "sepsis_stays", expected_config=config
        )
        shock = ArtifactStore(root / "40_labels").read_dataframe(
            "septic_shock_stays", expected_config=config
        )
        for frame, columns, name in (
            (cohort, {"subject_id", "hadm_id", "stay_id"}, "cohort_stays"),
            (pairs, {"hadm_id"}, "suspected_infection_pairs"),
            (sepsis, {"stay_id"}, "sepsis_stays"),
            (shock, {"stay_id", "septic_shock"}, "septic_shock_stays"),
        ):
            missing = sorted(columns - set(frame.columns))
            if missing:
                raise ValueError(
                    f"{name} is missing columns: {', '.join(missing)}"
                )
        selected = set(cohort["stay_id"])
        sepsis_ids = set(sepsis["stay_id"])
        shock_ids = set(shock["stay_id"])
        if not sepsis_ids <= selected or shock_ids != sepsis_ids:
            raise ValueError(
                f"Downstream stay sets are inconsistent for policy {policy}"
            )
        cohort_ids[policy] = selected
        landmark_rows = sum(
            manifests[name].rows
            for name in POLICY_PIPELINE_ARTIFACTS["50_landmarks"]
        )
        feature_rows = sum(
            manifests[name].rows
            for name in POLICY_PIPELINE_ARTIFACTS["60_features"]
        )
        rows.append({
            "policy": policy,
            "selected_icu_stays": len(cohort),
            "admissions": int(cohort["hadm_id"].nunique()),
            "patients": int(cohort["subject_id"].nunique()),
            "infection_pairs": len(pairs),
            "sepsis3_stays": len(sepsis),
            "shock_proxy_positive_stays": int(
                shock["septic_shock"].astype(bool).sum()
            ),
            "sofa_hourly_rows": manifests["sofa_hourly"].rows,
            "landmark_rows_all_targets_partitions": landmark_rows,
            "feature_rows_all_targets_partitions": feature_rows,
        })
        provenance[policy] = {
            "run_id": root.name,
            "config_sha256": next(iter(config_hashes)),
            "code_version": next(iter(code_versions)),
            "artifact_sha256": {
                name: manifest.sha256
                for name, manifest in sorted(manifests.items())
            },
        }

    if not (
        cohort_ids[StayPolicy.FIRST_PER_PATIENT.value]
        <= cohort_ids[StayPolicy.FIRST_PER_ADMISSION.value]
        <= cohort_ids[StayPolicy.ALL.value]
    ):
        raise ValueError("Policy runs violate the required cohort nesting")

    return {
        "schema_version": 1,
        "purpose": "D002_demo_full_pipeline_review_only",
        "distribution_class": "protected_aggregate_unsuppressed_counts",
        "clinical_status_mutated": False,
        "source": {"data_version": "2.2", "runs": provenance},
        "tables": {
            "downstream_policy_comparison": rows,
            "decision_evidence": [{
                "decision_id": "D002",
                "current_status": protocol_status["D002"],
                "evidence_in_report": "demo_full_pipeline_reconstruction",
                "remaining_requirement": (
                    "repeat on authorized full development data and obtain "
                    "clinical/methodological sign-off without selecting on test"
                ),
            }],
        },
    }
