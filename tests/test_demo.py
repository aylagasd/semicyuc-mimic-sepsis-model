from hashlib import sha256

import pytest

from mimic_sepsis.demo import file_sha256, parse_sha256_manifest


def test_parse_manifest_accepts_nested_file():
    digest = "a" * 64
    entry = parse_sha256_manifest(f"{digest} hosp/patients.csv.gz\n")[0]
    assert entry.sha256 == digest
    assert entry.relative_path.as_posix() == "hosp/patients.csv.gz"


@pytest.mark.parametrize("path", ["../secret", "/absolute", "hosp/../../secret"])
def test_parse_manifest_rejects_unsafe_paths(path):
    with pytest.raises(ValueError, match="Unsafe"):
        parse_sha256_manifest(f"{'a' * 64} {path}\n")


def test_file_sha256(tmp_path):
    path = tmp_path / "example"
    path.write_bytes(b"mimic")
    assert file_sha256(path) == sha256(b"mimic").hexdigest()
