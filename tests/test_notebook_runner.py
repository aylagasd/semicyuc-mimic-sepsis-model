from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

from mimic_sepsis.notebook_runner import (
    discover_notebooks, execute_notebooks, notebook_environment,
)


def _touch(path: Path) -> None:
    path.write_text("{}", encoding="utf-8")


def test_discovery_requires_one_notebook_per_number(tmp_path):
    _touch(tmp_path / "00_first.ipynb")
    _touch(tmp_path / "02_third.ipynb")
    with pytest.raises(FileNotFoundError, match="01"):
        discover_notebooks(tmp_path, start=0, end=2)

    _touch(tmp_path / "01_second.ipynb")
    assert [path.name for path in discover_notebooks(tmp_path, start=0, end=2)] == [
        "00_first.ipynb", "01_second.ipynb", "02_third.ipynb",
    ]


def test_discovery_rejects_duplicate_numbers(tmp_path):
    _touch(tmp_path / "00_first.ipynb")
    _touch(tmp_path / "00_other.ipynb")
    with pytest.raises(ValueError, match="duplicate"):
        discover_notebooks(tmp_path, start=0, end=0)


def test_environment_is_confined_to_project(tmp_path):
    existing_cache = tmp_path / ".cache"
    existing_cache.mkdir(mode=0o755)
    environment = notebook_environment(tmp_path)
    for name in (
        "XDG_CACHE_HOME", "IPYTHONDIR", "JUPYTER_CONFIG_DIR",
        "JUPYTER_DATA_DIR", "JUPYTER_RUNTIME_DIR",
    ):
        path = Path(environment[name])
        assert path.is_dir()
        path.relative_to(tmp_path)
        assert stat.S_IMODE(path.stat().st_mode) == 0o700


def test_execution_uses_clean_nbconvert_command_and_stops_on_failure(
    tmp_path, monkeypatch,
):
    notebooks = tmp_path / "notebooks"
    notebooks.mkdir()
    first = notebooks / "00_first.ipynb"
    second = notebooks / "01_second.ipynb"
    _touch(first)
    _touch(second)
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        if len(calls) == 2:
            raise __import__("subprocess").CalledProcessError(1, command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("mimic_sepsis.notebook_runner.subprocess.run", fake_run)
    with pytest.raises(__import__("subprocess").CalledProcessError):
        execute_notebooks(
            (first, second), project_root=tmp_path,
            output_dir=Path("derived"), timeout_seconds=123,
            python_executable="project-python",
        )

    assert len(calls) == 2
    assert calls[0][0][:3] == ["project-python", "-m", "nbconvert"]
    assert "--ExecutePreprocessor.timeout=123" in calls[0][0]
    assert calls[0][1]["check"] is True
    assert calls[0][1]["cwd"] == tmp_path.resolve()
    assert stat.S_IMODE((tmp_path / "derived").stat().st_mode) == 0o700
