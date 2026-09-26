from pathlib import Path
import subprocess

from mimic_sepsis.code_identity import detect_code_version


def git(repo: Path, *arguments: str) -> None:
    subprocess.run(["git", *arguments], cwd=repo, check=True, capture_output=True)


def test_dirty_code_identity_is_content_bound(tmp_path):
    git(tmp_path, "init")
    git(tmp_path, "config", "user.email", "test@example.invalid")
    git(tmp_path, "config", "user.name", "Test")
    tracked = tmp_path / "module.py"
    tracked.write_text("VALUE = 1\n", encoding="utf-8")
    git(tmp_path, "add", "module.py")
    git(tmp_path, "commit", "-m", "initial")

    clean = detect_code_version(tmp_path)
    tracked.write_text("VALUE = 2\n", encoding="utf-8")
    dirty_one = detect_code_version(tmp_path)
    tracked.write_text("VALUE = 3\n", encoding="utf-8")
    dirty_two = detect_code_version(tmp_path)

    assert "-dirty-" not in clean
    assert "-dirty-" in dirty_one
    assert dirty_one != dirty_two


def test_untracked_code_content_changes_identity(tmp_path):
    git(tmp_path, "init")
    git(tmp_path, "config", "user.email", "test@example.invalid")
    git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    git(tmp_path, "add", "tracked.txt")
    git(tmp_path, "commit", "-m", "initial")
    untracked = tmp_path / "new_module.py"
    untracked.write_text("VALUE = 1\n", encoding="utf-8")
    first = detect_code_version(tmp_path)
    untracked.write_text("VALUE = 2\n", encoding="utf-8")
    second = detect_code_version(tmp_path)
    assert first != second
