import json
import sys

import pandas as pd

from mimic_sepsis.report_artifacts import REPORT_TABLES, write_aggregate_report
from mimic_sepsis.reporting import DevelopmentReport
from scripts import validate_pretest_report


def _write_report(path):
    report = DevelopmentReport(**{
        name: pd.DataFrame({"metric": [name], "estimate": [0.5]})
        for name in REPORT_TABLES
    })
    return write_aggregate_report(
        report, path, data_version="3.1", code_version="abc1234",
        config={"source": "validation"},
    )


def test_cli_reports_only_aggregate_integrity_metadata(tmp_path, monkeypatch, capsys):
    manifest = _write_report(tmp_path)
    monkeypatch.setattr(sys, "argv", ["validate_pretest_report.py", str(tmp_path)])
    assert validate_pretest_report.main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["valid_aggregate_report"] is True
    assert output["report_sha256"] == manifest.report_sha256
    assert set(output["tables"]) == set(REPORT_TABLES)
    assert "subject_id" not in json.dumps(output)


def test_cli_fails_closed_for_invalid_report(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["validate_pretest_report.py", str(tmp_path)])
    assert validate_pretest_report.main() == 2
    output = json.loads(capsys.readouterr().out)
    assert output["valid_aggregate_report"] is False
