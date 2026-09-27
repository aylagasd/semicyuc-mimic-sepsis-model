"""Execute the canonical notebook sequence without modifying source notebooks."""

from __future__ import annotations

from collections.abc import Sequence
import os
from pathlib import Path
import subprocess
import sys


def discover_notebooks(
    notebook_dir: Path,
    *,
    start: int = 0,
    end: int = 13,
) -> tuple[Path, ...]:
    """Return a complete, uniquely numbered inclusive notebook range."""
    if start < 0 or end < start or end > 99:
        raise ValueError("notebook range must satisfy 0 <= start <= end <= 99")
    notebook_dir = Path(notebook_dir)
    found: dict[int, Path] = {}
    for path in sorted(notebook_dir.glob("[0-9][0-9]_*.ipynb")):
        number = int(path.name[:2])
        if number < start or number > end:
            continue
        if number in found:
            raise ValueError(f"duplicate notebook number: {number:02d}")
        found[number] = path
    missing = [number for number in range(start, end + 1) if number not in found]
    if missing:
        rendered = ", ".join(f"{number:02d}" for number in missing)
        raise FileNotFoundError(f"missing notebooks: {rendered}")
    return tuple(found[number] for number in range(start, end + 1))


def notebook_environment(project_root: Path) -> dict[str, str]:
    """Confine writable Jupyter/IPython state to ignored project directories."""
    root = Path(project_root).resolve()
    jupyter = root / ".jupyter"
    locations = {
        "XDG_CACHE_HOME": root / ".cache",
        "IPYTHONDIR": jupyter / "ipython",
        "JUPYTER_CONFIG_DIR": jupyter / "config",
        "JUPYTER_DATA_DIR": jupyter / "data",
        "JUPYTER_RUNTIME_DIR": jupyter / "runtime",
    }
    environment = os.environ.copy()
    for name, path in locations.items():
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.chmod(0o700)
        environment[name] = str(path)
    return environment


def execute_notebooks(
    notebooks: Sequence[Path],
    *,
    project_root: Path,
    output_dir: Path,
    timeout_seconds: int = 600,
    python_executable: str | Path = sys.executable,
) -> None:
    """Execute notebooks independently, stopping on the first failing kernel."""
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    root = Path(project_root).resolve()
    destination = Path(output_dir)
    if not destination.is_absolute():
        destination = root / destination
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination.chmod(0o700)
    environment = notebook_environment(root)
    for notebook in notebooks:
        source = Path(notebook).resolve()
        try:
            source.relative_to(root)
        except ValueError as exc:
            raise ValueError("notebooks must be inside project_root") from exc
        print(f"Executing {source.name}", flush=True)
        subprocess.run(
            [
                str(python_executable), "-m", "nbconvert",
                "--to", "notebook", "--execute",
                f"--ExecutePreprocessor.timeout={timeout_seconds}",
                "--output-dir", str(destination), str(source),
            ],
            cwd=root,
            env=environment,
            check=True,
        )
