import gzip

from mimic_sepsis.deployment import preflight_mimic_files


def _write_gzip(path, header):
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as stream:
        stream.write(",".join(header) + "\n")


def test_preflight_reads_only_headers_and_reports_ready(tmp_path):
    requirements = {
        "hosp/patients.csv.gz": ("subject_id", "anchor_age"),
        "icu/icustays.csv.gz": ("subject_id", "stay_id"),
    }
    for relative, columns in requirements.items():
        _write_gzip(tmp_path / relative, [*columns, "extra"])
    report = preflight_mimic_files(tmp_path, requirements=requirements)
    assert report.ready
    assert report.present_files == 2
    assert report.compressed_bytes > 0


def test_preflight_reports_missing_and_schema_drift(tmp_path):
    requirements = {
        "hosp/patients.csv.gz": ("subject_id", "anchor_age"),
        "icu/icustays.csv.gz": ("subject_id", "stay_id"),
    }
    _write_gzip(tmp_path / "hosp/patients.csv.gz", ["subject_id"])
    report = preflight_mimic_files(tmp_path, requirements=requirements)
    assert not report.ready
    assert report.missing_files == ("icu/icustays.csv.gz",)
    assert report.missing_columns["hosp/patients.csv.gz"] == ("anchor_age",)


def test_preflight_rejects_invalid_space_requirement(tmp_path):
    try:
        preflight_mimic_files(tmp_path, minimum_free_gb=-1, requirements={})
    except ValueError as error:
        assert "non-negative" in str(error)
    else:
        raise AssertionError("negative minimum_free_gb must fail")
