import json

import pandas as pd
import pytest

from mimic_sepsis.artifacts import ArtifactStore, ArtifactValidationError


def test_round_trip_creates_parquet_and_manifest(tmp_path):
    store = ArtifactStore(tmp_path / "data" / "derived")
    source = pd.DataFrame({"stay_id": [1, 2], "sofa": [3.0, None]})

    manifest = store.write_dataframe(
        "sofa_hourly",
        source,
        data_version="mimic-iv-demo-2.2",
        code_version="abc123",
        config={"window_hours": 24},
    )
    result = store.read_dataframe(
        "sofa_hourly", expected_config={"window_hours": 24}
    )

    assert manifest.rows == 2
    assert manifest.columns == ["stay_id", "sofa"]
    pd.testing.assert_frame_equal(result, source)
    assert (store.root / "sofa_hourly.parquet").exists()
    payload = json.loads(
        (store.root / "sofa_hourly.manifest.json").read_text(encoding="utf-8")
    )
    assert payload["data_version"] == "mimic-iv-demo-2.2"
    assert len(payload["sha256"]) == 64


def test_config_hash_is_order_independent_and_mismatch_is_rejected(tmp_path):
    store = ArtifactStore(tmp_path)
    store.write_dataframe(
        "cohort",
        pd.DataFrame({"id": [1]}),
        data_version="2.2",
        code_version="test",
        config={"a": 1, "b": 2},
    )

    store.validate("cohort", expected_config={"b": 2, "a": 1})
    with pytest.raises(ArtifactValidationError, match="configuration"):
        store.validate("cohort", expected_config={"a": 9, "b": 2})


def test_corrupt_parquet_is_detected_before_read(tmp_path):
    store = ArtifactStore(tmp_path)
    store.write_dataframe(
        "labs",
        pd.DataFrame({"value": [1.0]}),
        data_version="2.2",
        code_version="test",
    )
    with (tmp_path / "labs.parquet").open("ab") as stream:
        stream.write(b"corrupt")

    with pytest.raises(ArtifactValidationError, match="checksum"):
        store.read_dataframe("labs")


def test_manifest_shape_tampering_is_detected(tmp_path):
    store = ArtifactStore(tmp_path)
    store.write_dataframe(
        "renal",
        pd.DataFrame({"stay_id": [1]}),
        data_version="2.2",
        code_version="test",
    )
    path = tmp_path / "renal.manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["rows"] = 99
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ArtifactValidationError, match="shape"):
        store.validate("renal")


@pytest.mark.parametrize("name", ["../escape", "a/b", "", ".hidden"])
def test_unsafe_artifact_names_are_rejected(tmp_path, name):
    store = ArtifactStore(tmp_path)
    with pytest.raises(ValueError):
        store.write_dataframe(
            name,
            pd.DataFrame(),
            data_version="2.2",
            code_version="test",
        )


def test_rewrite_replaces_existing_artifact(tmp_path):
    store = ArtifactStore(tmp_path)
    arguments = {"data_version": "2.2", "code_version": "test"}
    store.write_dataframe("grid", pd.DataFrame({"x": [1]}), **arguments)
    store.write_dataframe("grid", pd.DataFrame({"x": [2, 3]}), **arguments)

    assert store.validate("grid").rows == 2
    assert store.read_dataframe("grid")["x"].tolist() == [2, 3]
    assert not list(tmp_path.glob(".artifact-*"))
