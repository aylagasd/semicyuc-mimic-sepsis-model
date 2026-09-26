import json
from pathlib import Path

import pandas as pd
import pytest

from mimic_sepsis.artifacts import ArtifactStore, ArtifactValidationError
from mimic_sepsis.phenotype_evidence import (
    ValidatedPhenotypeSource,
    build_phenotype_evidence,
    evidence_sha256,
    load_validated_phenotype_source,
    read_phenotype_evidence,
    write_phenotype_evidence,
)
from mimic_sepsis.sepsis_labels import EPISODE_COLUMNS
from mimic_sepsis.septic_shock import SHOCK_COLUMNS


STATUSES = {
    "D002": "provisional",
    "D004": "provisional",
    "D010": "provisional",
    "D011": "pending",
}


def _tables() -> dict[str, pd.DataFrame]:
    pairs = pd.DataFrame({
        "subject_id": [10, 20],
        "hadm_id": [100, 200],
        "antibiotic_id": [1, 2],
        "culture_id": [11, 22],
        "pair_direction": ["antibiotic_first", "culture_first"],
    })
    rows = []
    for index, (subject, admission, stay, covered, complete) in enumerate([
        (10, 100, 1000, True, 0),
        (20, 200, 2000, False, 2),
    ]):
        row = {column: pd.NA for column in EPISODE_COLUMNS}
        row.update({
            "subject_id": subject,
            "hadm_id": admission,
            "antibiotic_id": index + 1,
            "culture_id": (index + 1) * 11,
            "stay_id": stay,
            "t_si": pd.Timestamp("2020-01-01") + pd.Timedelta(index, unit="D"),
            "t0": pd.Timestamp("2020-01-01 01:00") + pd.Timedelta(index, unit="D"),
            "sepsis3": True,
            "baseline_assumed_zero": False,
            "acute_window_covered": covered,
            "missing_components_at_t0": complete,
            "exclusion_reason": pd.NA,
        })
        rows.append(row)
    episodes = pd.DataFrame(rows, columns=EPISODE_COLUMNS)
    shock_rows = []
    for index, episode in episodes.iterrows():
        row = {column: pd.NA for column in SHOCK_COLUMNS}
        row.update({
            "subject_id": episode["subject_id"],
            "hadm_id": episode["hadm_id"],
            "stay_id": episode["stay_id"],
            "septic_shock": index == 0,
            "adequate_fluids_verified": False,
        })
        shock_rows.append(row)
    return {
        "suspected_infection_pairs": pairs,
        "sepsis_episodes": episodes,
        "sepsis_stays": episodes.copy(),
        "septic_shock_stays": pd.DataFrame(shock_rows, columns=SHOCK_COLUMNS),
    }


def _source() -> ValidatedPhenotypeSource:
    return ValidatedPhenotypeSource(
        layout="test",
        data_version="2.2",
        config_sha256="a" * 64,
        artifact_sha256={
            name: str(index) * 64
            for index, name in enumerate(_tables(), 1)
        },
        tables=_tables(),
    )


def test_evidence_is_aggregate_content_and_does_not_freeze_status():
    content = build_phenotype_evidence(_source(), protocol_status=STATUSES)
    assert content["clinical_status_mutated"] is False
    assert content["source"]["data_version"] == "2.2"
    for rows in content["tables"].values():
        assert not ({"subject_id", "hadm_id", "stay_id"} & set(rows[0]))
    decisions = {
        row["decision_id"]: row for row in content["tables"]["decision_evidence"]
    }
    assert decisions["D011"]["current_status"] == "pending"


def test_evidence_round_trip_is_content_bound_and_private(tmp_path):
    content = build_phenotype_evidence(_source(), protocol_status=STATUSES)
    path = tmp_path / "evidence.json"
    digest = write_phenotype_evidence(path, content)
    loaded = read_phenotype_evidence(path)
    assert loaded["report_sha256"] == digest == evidence_sha256(content)
    assert path.stat().st_mode & 0o777 == 0o600

    document = json.loads(path.read_text(encoding="utf-8"))
    document["content"]["purpose"] = "tampered"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ArtifactValidationError, match="checksum"):
        read_phenotype_evidence(path)


def test_demo_source_loader_validates_all_four_artifacts(tmp_path):
    label_root = tmp_path / "run" / "40_labels"
    store = ArtifactStore(label_root)
    config = {"definition": "test"}
    for name, frame in _tables().items():
        store.write_dataframe(
            name, frame, data_version="2.2", code_version="test", config=config
        )
    loaded = load_validated_phenotype_source(tmp_path / "run")
    assert loaded.layout == "demo_artifact_store"
    assert loaded.data_version == "2.2"
    assert set(loaded.tables) == set(_tables())

    path = label_root / "sepsis_episodes.parquet"
    path.write_bytes(path.read_bytes() + b"tampered")
    with pytest.raises(ArtifactValidationError, match="checksum"):
        load_validated_phenotype_source(tmp_path / "run")


def test_evidence_requires_every_governed_decision_status():
    with pytest.raises(ValueError, match="D011"):
        build_phenotype_evidence(
            _source(),
            protocol_status={
                key: value for key, value in STATUSES.items() if key != "D011"
            },
        )
