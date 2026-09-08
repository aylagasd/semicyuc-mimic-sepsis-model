"""Download and query the public MIMIC-IV demo without committing data."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path, PurePosixPath
from urllib.request import urlopen


DEMO_VERSION = "2.2"
DEMO_BASE_URL = f"https://physionet.org/files/mimic-iv-demo/{DEMO_VERSION}"


@dataclass(frozen=True)
class ManifestEntry:
    """One file and its expected SHA-256 digest."""

    sha256: str
    relative_path: PurePosixPath


def parse_sha256_manifest(content: str) -> tuple[ManifestEntry, ...]:
    """Parse PhysioNet's SHA256SUMS file, rejecting unsafe paths."""
    entries: list[ManifestEntry] = []
    for line_number, line in enumerate(content.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            digest, raw_path = line.split(maxsplit=1)
        except ValueError as exc:
            raise ValueError(f"Invalid manifest line {line_number}") from exc
        relative_path = PurePosixPath(raw_path.lstrip("*"))
        if (
            len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest.lower())
            or relative_path.is_absolute()
            or ".." in relative_path.parts
        ):
            raise ValueError(f"Unsafe manifest line {line_number}")
        entries.append(ManifestEntry(digest.lower(), relative_path))
    if not entries:
        raise ValueError("The manifest is empty")
    return tuple(entries)


def file_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Return the SHA-256 digest of a local file without loading it into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def download_demo(
    destination: Path,
    *,
    base_url: str = DEMO_BASE_URL,
    force: bool = False,
) -> tuple[Path, ...]:
    """Download every public demo file and verify it against PhysioNet hashes."""
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    manifest_url = f"{base_url.rstrip('/')}/SHA256SUMS.txt"
    with urlopen(manifest_url, timeout=60) as response:  # noqa: S310 - fixed/explicit URL
        manifest_content = response.read().decode("utf-8")
    entries = parse_sha256_manifest(manifest_content)
    (destination / "SHA256SUMS.txt").write_text(manifest_content, encoding="utf-8")

    downloaded: list[Path] = []
    for entry in entries:
        target = destination.joinpath(*entry.relative_path.parts)
        if target.exists() and not force and file_sha256(target) == entry.sha256:
            downloaded.append(target)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".part")
        url = f"{base_url.rstrip('/')}/{entry.relative_path.as_posix()}"
        with urlopen(url, timeout=120) as response, temporary.open("wb") as output:  # noqa: S310
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
        if file_sha256(temporary) != entry.sha256:
            temporary.unlink(missing_ok=True)
            raise ValueError(f"Checksum mismatch for {entry.relative_path}")
        temporary.replace(target)
        downloaded.append(target)
    return tuple(downloaded)
