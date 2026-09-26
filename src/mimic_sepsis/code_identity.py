"""Stable Git code identities for reproducible artifact run directories."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path, PurePosixPath
import subprocess


def _git(repo: Path, *arguments: str) -> bytes:
    return subprocess.run(
        ["git", *arguments], cwd=repo, check=True, capture_output=True
    ).stdout


def detect_code_version(repo: Path) -> str:
    """Return commit identity plus a content hash for any dirty worktree.

    Only the digest is returned; diff contents and untracked file contents are
    never logged. Ignored files (including data and local credentials) are not
    part of the identity.
    """
    root = Path(repo)
    try:
        commit = _git(root, "rev-parse", "--short=12", "HEAD").decode().strip()
        tracked_diff = _git(
            root, "diff", "--binary", "--no-ext-diff", "HEAD", "--", "."
        )
        untracked_raw = _git(
            root, "ls-files", "--others", "--exclude-standard", "-z"
        )
    except (OSError, subprocess.CalledProcessError, UnicodeDecodeError):
        return "unknown"

    untracked = sorted(
        item for item in untracked_raw.decode("utf-8", errors="surrogateescape").split("\0")
        if item
    )
    if not tracked_diff and not untracked:
        return commit

    digest = hashlib.sha256()
    digest.update(b"tracked-diff\0")
    digest.update(tracked_diff)
    for relative in untracked:
        pure = PurePosixPath(relative)
        if pure.is_absolute() or ".." in pure.parts:
            raise ValueError("Git returned an unsafe untracked path")
        path = root / Path(*pure.parts)
        digest.update(b"untracked-path\0")
        digest.update(relative.encode("utf-8", errors="surrogateescape"))
        digest.update(b"\0")
        if path.is_symlink():
            digest.update(b"symlink\0")
            digest.update(os.readlink(path).encode("utf-8", errors="surrogateescape"))
        elif path.is_file():
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
        else:
            digest.update(b"non-file")
    return f"{commit}-dirty-{digest.hexdigest()[:12]}"
