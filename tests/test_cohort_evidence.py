from pathlib import Path

import pandas as pd
import pytest

from mimic_sepsis.artifacts import ArtifactStore
from mimic_sepsis.cohort_evidence import (
    POLICY_PIPELINE_ARTIFACTS, build_cohort_policy_evidence,
    build_demo_policy_outcome_evidence,
    load_cohort_sources,
)


def _tables():
    patients = pd.DataFrame({
        "subject_id": [1, 2],
        "anchor_age": [50, 17],
        "anchor_year": [2100, 2100],
    })
    admissions = pd.DataFrame({
        "subject_id": [1, 1, 2],
        "hadm_id": [10, 11, 20],
    })
    icustays = pd.DataFrame({
        "subject_id": [1, 1, 1, 2],
        "hadm_id": [10, 10, 11, 20],
        "stay_id": [100, 101, 102, 200],
        "intime": [
            "2100-01-01", "2100-01-02", "2100-02-01", "2100-01-01",
        ],
        "outtime": [
            "2100-01-02", "2100-01-03", "2100-02-02", "2100-01-02",
        ],
    })
    return patients, admissions, icustays


def test_cohort_evidence_rebuilds_nested_policies_without_identifiers():
    content = build_cohort_policy_evidence(
        *_tables(),
        data_version="demo",
        source_sha256={"patients": "a", "admissions": "b", "icustays": "c"},
        protocol_status={"D002": "provisional"},
        policies=["first_per_admission", "first_per_patient", "all"],
    )
    flows = {row["policy"]: row for row in content["tables"]["cohort_flow"]}
    assert flows["first_per_admission"]["selected_icu_stays"] == 2
    assert flows["first_per_patient"]["selected_icu_stays"] == 1
    assert flows["all"]["selected_icu_stays"] == 3
    for rows in content["tables"].values():
        assert not ({"subject_id", "hadm_id", "stay_id"} & set(rows[0]))
    assert content["clinical_status_mutated"] is False


def test_cohort_evidence_rejects_unreviewed_policy_order():
    with pytest.raises(ValueError, match="predeclared"):
        build_cohort_policy_evidence(
            *_tables(),
            data_version="demo",
            source_sha256={},
            protocol_status={"D002": "provisional"},
            policies=["all", "first_per_patient", "first_per_admission"],
        )


def test_cohort_source_loader_projects_columns_and_hashes(tmp_path):
    patients, admissions, icustays = _tables()
    frames = {
        "patients": patients.assign(extra="not loaded"),
        "admissions": admissions.assign(extra="not loaded"),
        "icustays": icustays.assign(extra="not loaded"),
    }
    paths = {
        "patients": tmp_path / "hosp" / "patients.csv.gz",
        "admissions": tmp_path / "hosp" / "admissions.csv.gz",
        "icustays": tmp_path / "icu" / "icustays.csv.gz",
    }
    for name, path in paths.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        frames[name].to_csv(path, index=False)
    loaded, hashes = load_cohort_sources(
        tmp_path, memory_limit="256MB", temp_dir=tmp_path / "tmp"
    )
    assert set(loaded["patients"]) == {"subject_id", "anchor_age", "anchor_year"}
    assert set(loaded["admissions"]) == {"subject_id", "hadm_id"}
    assert set(loaded["icustays"]) == {
        "subject_id", "hadm_id", "stay_id", "intime", "outtime",
    }
    assert set(hashes) == set(paths)


def test_cohort_source_loader_fails_before_partial_read(tmp_path):
    with pytest.raises(FileNotFoundError, match="admissions"):
        load_cohort_sources(tmp_path)


def _write_policy_run(root, policy, stay_ids):
    config = {"cohort": {"stay_policy": policy}}
    cohort = pd.DataFrame({
        "subject_id": list(range(1, len(stay_ids) + 1)),
        "hadm_id": list(range(10, 10 + len(stay_ids))),
        "stay_id": stay_ids,
    })
    frames = {
        "cohort_stays": cohort,
        "sofa_hourly": pd.DataFrame({"stay_id": [stay_ids[0]]}),
        "suspected_infection_pairs": pd.DataFrame({"hadm_id": [10]}),
        "sepsis_stays": pd.DataFrame({"stay_id": [stay_ids[0]]}),
        "septic_shock_stays": pd.DataFrame({
            "stay_id": [stay_ids[0]], "septic_shock": [True],
        }),
    }
    for directory, names in POLICY_PIPELINE_ARTIFACTS.items():
        store = ArtifactStore(root / directory)
        for name in names:
            frame = frames.get(name, pd.DataFrame({"synthetic_row": [1]}))
            store.write_dataframe(
                name, frame, data_version="2.2",
                code_version="test-commit", config=config,
            )
    return config


def test_demo_policy_outcomes_validate_complete_runs_without_identifiers(tmp_path):
    policies = ["first_per_admission", "first_per_patient", "all"]
    stay_ids = {
        "first_per_admission": [100, 101],
        "first_per_patient": [100],
        "all": [100, 101, 102],
    }
    private_marker = "private_institution_host"
    roots = {
        policy: tmp_path / private_marker / policy for policy in policies
    }
    configs = {
        policy: _write_policy_run(roots[policy], policy, stay_ids[policy])
        for policy in policies
    }

    content = build_demo_policy_outcome_evidence(
        roots,
        expected_configs=configs,
        protocol_status={"D002": "provisional"},
    )

    rows = content["tables"]["downstream_policy_comparison"]
    assert [row["selected_icu_stays"] for row in rows] == [2, 1, 3]
    assert all(row["sepsis3_stays"] == 1 for row in rows)
    assert content["clinical_status_mutated"] is False
    assert private_marker not in str(content)
    for table in content["tables"].values():
        assert not ({"subject_id", "hadm_id", "stay_id"} & set(table[0]))


def test_demo_policy_outcomes_reject_non_nested_complete_runs(tmp_path):
    policies = ["first_per_admission", "first_per_patient", "all"]
    stay_ids = {
        "first_per_admission": [100],
        "first_per_patient": [999],
        "all": [100, 999],
    }
    roots = {policy: tmp_path / policy for policy in policies}
    configs = {
        policy: _write_policy_run(roots[policy], policy, stay_ids[policy])
        for policy in policies
    }
    with pytest.raises(ValueError, match="nesting"):
        build_demo_policy_outcome_evidence(
            roots,
            expected_configs=configs,
            protocol_status={"D002": "provisional"},
        )
