"""Credential-free readiness checks for the notebook analysis environment."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from importlib import metadata
import shutil
import subprocess
import sys
from typing import Any, Mapping, Sequence


PYTHON_DISTRIBUTIONS = (
    "duckdb",
    "pandas",
    "scikit-learn",
    "matplotlib",
    "nbformat",
    "nbclient",
    "jupyterlab",
)
REQUIRED_EXECUTABLES = ("jupyter", "Rscript")
R_PACKAGES = (
    "ggplot2",
    "DBI",
    "dplyr",
    "tidyr",
    "readr",
    "scales",
    "here",
    "IRkernel",
    "renv",
)


@dataclass(frozen=True)
class AnalysisEnvironmentReport:
    """Software-only report; never includes paths, credentials, or data."""

    ready: bool
    blockers: tuple[str, ...]
    python_version: str
    python_packages: Mapping[str, str | None]
    executables: Mapping[str, bool]
    r_probe_ok: bool
    r_version: str | None
    r_packages: Mapping[str, bool]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def audit_analysis_environment(
    *,
    python_version_info: Sequence[int],
    python_packages: Mapping[str, str | None],
    executables: Mapping[str, bool],
    r_probe_ok: bool,
    r_version: str | None,
    r_packages: Mapping[str, bool],
) -> AnalysisEnvironmentReport:
    """Validate the software contract used by notebooks 00--13."""
    if len(python_version_info) < 2:
        raise ValueError("python_version_info must contain major and minor")
    version = tuple(int(item) for item in python_version_info[:3])
    blockers: list[str] = []
    if version[:2] < (3, 11):
        blockers.append("python:version_below_3.11")
    for package in PYTHON_DISTRIBUTIONS:
        if not python_packages.get(package):
            blockers.append(f"python:{package}:missing")
    for executable in REQUIRED_EXECUTABLES:
        if executables.get(executable) is not True:
            blockers.append(f"executable:{executable}:missing")
    if executables.get("Rscript") is True:
        if not r_probe_ok:
            blockers.append("r:probe_failed")
        else:
            if not r_version:
                blockers.append("r:version_unavailable")
            for package in R_PACKAGES:
                if r_packages.get(package) is not True:
                    blockers.append(f"r:{package}:missing")

    unique_blockers = tuple(dict.fromkeys(blockers))
    return AnalysisEnvironmentReport(
        ready=not unique_blockers,
        blockers=unique_blockers,
        python_version=".".join(str(item) for item in version),
        python_packages={
            package: python_packages.get(package)
            for package in PYTHON_DISTRIBUTIONS
        },
        executables={
            executable: executables.get(executable) is True
            for executable in REQUIRED_EXECUTABLES
        },
        r_probe_ok=bool(r_probe_ok),
        r_version=r_version,
        r_packages={package: r_packages.get(package) is True for package in R_PACKAGES},
    )


def _probe_r(rscript: str | None) -> tuple[bool, str | None, dict[str, bool]]:
    if rscript is None:
        return False, None, {}
    package_vector = ",".join(f'"{package}"' for package in R_PACKAGES)
    expression = (
        f"packages <- c({package_vector}); "
        "cat('R_VERSION=', as.character(getRversion()), '\\n', sep=''); "
        "for (package in packages) "
        "cat('PACKAGE=', package, '=', "
        "ifelse(requireNamespace(package, quietly=TRUE), '1', '0'), "
        "'\\n', sep='')"
    )
    try:
        completed = subprocess.run(
            [rscript, "--vanilla", "-e", expression],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return False, None, {}
    if completed.returncode != 0:
        return False, None, {}
    r_version: str | None = None
    packages: dict[str, bool] = {}
    for line in completed.stdout.splitlines():
        if line.startswith("R_VERSION="):
            r_version = line.removeprefix("R_VERSION=") or None
        elif line.startswith("PACKAGE="):
            payload = line.removeprefix("PACKAGE=")
            package, separator, value = payload.rpartition("=")
            if separator and package in R_PACKAGES:
                packages[package] = value == "1"
    return True, r_version, packages


def inspect_analysis_environment() -> AnalysisEnvironmentReport:
    """Collect installed software versions and execute a namespace-only R probe."""
    packages: dict[str, str | None] = {}
    for package in PYTHON_DISTRIBUTIONS:
        try:
            packages[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            packages[package] = None
    executable_paths = {
        executable: shutil.which(executable)
        for executable in REQUIRED_EXECUTABLES
    }
    r_probe_ok, r_version, r_packages = _probe_r(executable_paths["Rscript"])
    return audit_analysis_environment(
        python_version_info=sys.version_info[:3],
        python_packages=packages,
        executables={key: value is not None for key, value in executable_paths.items()},
        r_probe_ok=r_probe_ok,
        r_version=r_version,
        r_packages=r_packages,
    )
