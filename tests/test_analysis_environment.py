from mimic_sepsis.analysis_environment import (
    PYTHON_DISTRIBUTIONS, REQUIRED_EXECUTABLES, R_PACKAGES,
    audit_analysis_environment,
)


def _audit(**overrides):
    values = {
        "python_version_info": (3, 13, 5),
        "python_packages": {package: "1.0" for package in PYTHON_DISTRIBUTIONS},
        "executables": {name: True for name in REQUIRED_EXECUTABLES},
        "r_probe_ok": True,
        "r_version": "4.5.1",
        "r_packages": {package: True for package in R_PACKAGES},
    }
    values.update(overrides)
    return audit_analysis_environment(**values)


def test_complete_analysis_environment_is_ready_and_aggregate_only():
    report = _audit()
    assert report.ready
    assert report.blockers == ()
    assert report.python_version == "3.13.5"
    assert "path" not in report.to_dict()


def test_environment_reports_python_jupyter_and_r_package_blockers():
    packages = {package: "1.0" for package in PYTHON_DISTRIBUTIONS}
    packages["scikit-learn"] = None
    r_packages = {package: True for package in R_PACKAGES}
    r_packages["ggplot2"] = False
    report = _audit(
        python_version_info=(3, 10, 9),
        python_packages=packages,
        executables={"jupyter": False, "Rscript": True},
        r_packages=r_packages,
    )
    assert not report.ready
    assert set(report.blockers) == {
        "python:version_below_3.11",
        "python:scikit-learn:missing",
        "executable:jupyter:missing",
        "r:ggplot2:missing",
    }


def test_missing_rscript_does_not_claim_each_r_package_is_missing():
    report = _audit(
        executables={"jupyter": True, "Rscript": False},
        r_probe_ok=False,
        r_version=None,
        r_packages={},
    )
    assert report.blockers == ("executable:Rscript:missing",)


def test_failed_r_probe_fails_closed():
    report = _audit(r_probe_ok=False, r_version=None, r_packages={})
    assert report.blockers == ("r:probe_failed",)
