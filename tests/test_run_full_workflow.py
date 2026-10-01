import subprocess

import pytest

from scripts.run_full_workflow import (
    WorkflowCommand, WorkflowStageError, build_workflow_commands,
    run_workflow_commands,
)


def _profile(path):
    path.write_text(
        '{"schema_version": 1, "duckdb_memory_limit": "8GB", '
        '"maximum_parallel_workers": 2}',
        encoding="utf-8",
    )


def test_extract_plan_uses_profile_and_stops_before_clinical_pipeline(tmp_path):
    profile = tmp_path / "compute.json"
    _profile(profile)
    commands = build_workflow_commands(
        repo=tmp_path,
        python="python",
        data_dir=tmp_path / "mimic",
        data_version="3.1",
        work_root=tmp_path / "work",
        temp_dir=tmp_path / "temp",
        compute_profile=profile,
        minimum_free_gb=100,
        minimum_age=18,
        stay_policy="first_per_admission",
        through="extract",
        resume=True,
    )
    assert [command.stage for command in commands] == ["preflight", "extract"]
    extract = commands[1].argv
    assert extract[extract.index("--memory-limit") + 1] == "8GB"
    assert extract[extract.index("--threads") + 1] == "2"
    assert extract[-1] == "--resume"


def test_validate_plan_runs_all_stages_and_targets_canonical_report(tmp_path):
    profile = tmp_path / "compute.json"
    _profile(profile)
    commands = build_workflow_commands(
        repo=tmp_path,
        python="python",
        data_dir=tmp_path / "mimic",
        data_version="3.1",
        work_root=tmp_path / "work",
        temp_dir=tmp_path / "temp",
        compute_profile=profile,
        minimum_free_gb=0,
        minimum_age=18,
        stay_policy="first_per_admission",
        through="validate",
        resume=False,
    )
    assert [command.stage for command in commands] == list(
        ("preflight", "extract", "pipeline", "validate")
    )
    assert str(tmp_path / "work" / "full_pipeline" / "resource_report.json") in (
        commands[-1].argv
    )
    assert all("--resume" not in command.argv for command in commands)


def test_runner_stops_at_first_failure_without_starting_later_stages():
    commands = (
        WorkflowCommand("preflight", ("python", "preflight.py")),
        WorkflowCommand("extract", ("python", "extract.py")),
        WorkflowCommand("pipeline", ("python", "pipeline.py")),
    )
    called = []

    def runner(argv, *, check):
        called.append((argv, check))
        return subprocess.CompletedProcess(argv, 7 if "extract.py" in argv else 0)

    with pytest.raises(WorkflowStageError) as caught:
        run_workflow_commands(commands, runner=runner)
    assert caught.value.stage == "extract"
    assert caught.value.completed == ("preflight",)
    assert caught.value.exit_code == 7
    assert [argv[0][1] for argv in called] == ["preflight.py", "extract.py"]


@pytest.mark.parametrize("minimum_free_gb", [-1, -0.1])
def test_plan_rejects_negative_disk_reserve(tmp_path, minimum_free_gb):
    profile = tmp_path / "compute.json"
    _profile(profile)
    with pytest.raises(ValueError, match="non-negative"):
        build_workflow_commands(
            repo=tmp_path,
            python="python",
            data_dir=tmp_path / "mimic",
            data_version="3.1",
            work_root=tmp_path / "work",
            temp_dir=tmp_path / "temp",
            compute_profile=profile,
            minimum_free_gb=minimum_free_gb,
            minimum_age=18,
            stay_policy="first_per_admission",
            through="preflight",
            resume=False,
        )
