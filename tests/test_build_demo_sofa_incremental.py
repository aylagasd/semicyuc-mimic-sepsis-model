import importlib.util
from pathlib import Path

import pandas as pd

_SCRIPT = Path(__file__).parents[1] / "scripts" / "build_demo_sofa_incremental.py"
_SPEC = importlib.util.spec_from_file_location("build_demo_sofa_incremental", _SCRIPT)
assert _SPEC and _SPEC.loader
cli = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(cli)


def test_run_id_is_stable_and_does_not_contain_credentials():
    config = cli.canonical_config()
    first = cli.make_run_id(config)
    second = cli.make_run_id(dict(reversed(list(config.items()))))
    assert first == second
    assert first.startswith("demo-2.2-v2.4.0-")
    assert "password" not in config


def test_cohort_stage_writes_canonical_artifacts(tmp_path, monkeypatch):
    stays = pd.DataFrame({
        "subject_id": [1], "hadm_id": [10], "stay_id": [100],
        "intime": ["2100-01-01"], "outtime": ["2100-01-02"],
    })
    chart = pd.DataFrame({
        "stay_id": [100], "itemid": [220045],
        "charttime": ["2100-01-01"], "valuenum": [80],
    })
    monkeypatch.setattr(
        cli, "read_demo_tables",
        lambda data_dir, names=cli.RAW_TABLES: {
            "icustays": stays, "chartevents": chart
        },
    )
    config = cli.canonical_config()
    cli.build_cohort_stage(
        data_dir=tmp_path, run_root=tmp_path / "run", config=config,
        code_version="test", resume=False,
    )
    store = cli.ArtifactStore(tmp_path / "run" / "00_cohort")
    assert store.validate("cohort_stays", expected_config=config).rows == 1
    assert store.validate("hourly_grid", expected_config=config).rows > 0


def test_resume_skips_valid_cohort_stage(tmp_path, monkeypatch):
    calls = 0
    stays = pd.DataFrame({
        "subject_id": [1], "hadm_id": [10], "stay_id": [100],
        "intime": ["2100-01-01"], "outtime": ["2100-01-02"],
    })
    chart = pd.DataFrame({
        "stay_id": [100], "itemid": [220045],
        "charttime": ["2100-01-01"], "valuenum": [80],
    })

    def loader(data_dir, names=cli.RAW_TABLES):
        nonlocal calls
        calls += 1
        return {"icustays": stays, "chartevents": chart}

    monkeypatch.setattr(cli, "read_demo_tables", loader)
    kwargs = {
        "data_dir": tmp_path, "run_root": tmp_path / "run",
        "config": cli.canonical_config(), "code_version": "test",
    }
    cli.build_cohort_stage(**kwargs, resume=False)
    cli.build_cohort_stage(**kwargs, resume=True)
    assert calls == 1


def test_score_stage_writes_components_and_final(tmp_path, monkeypatch):
    config = cli.canonical_config()
    cohort_store = cli.ArtifactStore(tmp_path / "run" / "00_cohort")
    cohort_store.write_dataframe(
        "hourly_grid", pd.DataFrame({"stay_id": [1], "hr": [0]}),
        data_version="2.2", code_version="test", config=config,
    )
    result = pd.DataFrame({
        "subject_id": [1], "hadm_id": [10], "stay_id": [1], "hr": [0],
        "endtime": pd.to_datetime(["2100-01-01"]),
        **{f"sofa_{name}": pd.array([1], dtype="Int64") for name in cli.COMPONENTS},
        "missing_components": pd.array([0], dtype="Int64"),
        "sofa_complete": pd.array([6], dtype="Int64"),
        "sofa_total": pd.array([6], dtype="Int64"),
    })
    monkeypatch.setattr(cli, "read_demo_tables", lambda *args, **kwargs: {})
    monkeypatch.setattr(cli, "build_demo_hourly_sofa", lambda **tables: result)
    cli.build_score_stage(
        data_dir=tmp_path, run_root=tmp_path / "run", config=config,
        code_version="test", resume=False,
    )
    score_store = cli.ArtifactStore(tmp_path / "run" / "30_score")
    assert score_store.validate("sofa_hourly", expected_config=config).rows == 1
    component_store = cli.ArtifactStore(tmp_path / "run" / "20_components")
    component = component_store.read_dataframe(
        "renal_hourly", expected_config=config
    )
    assert component.loc[0, "score_24h"] == 1
    assert pd.isna(component.loc[0, "source_event_count_24h"])
