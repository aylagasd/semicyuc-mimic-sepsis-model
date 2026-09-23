#!/usr/bin/env python3
"""Create a non-authorizing model-freeze draft and print unresolved blockers."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from mimic_sepsis.artifacts import ArtifactError
from mimic_sepsis.freeze_preparation import prepare_model_freeze_draft


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report_root", type=Path)
    parser.add_argument(
        "--protocol-status", type=Path,
        default=Path("config/protocol_status.json"),
    )
    parser.add_argument(
        "--selection", type=Path,
        help="Optional reviewed JSON with model, parameters, calibration and thresholds.",
    )
    parser.add_argument(
        "--output", type=Path,
        help="Optional path for the draft JSON; it is never marked frozen.",
    )
    return parser.parse_args()


def _git_state(repo: Path) -> tuple[str, bool]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, check=True,
        capture_output=True, text=True,
    ).stdout
    return commit, not status.strip()


def main() -> int:
    args = parse_args()
    repo = Path(__file__).resolve().parents[1]
    try:
        protocol = json.loads(args.protocol_status.read_text(encoding="utf-8"))
        selection = (
            json.loads(args.selection.read_text(encoding="utf-8"))
            if args.selection else None
        )
        commit, clean = _git_state(repo)
        result = prepare_model_freeze_draft(
            str(args.report_root), protocol, code_commit=commit,
            worktree_clean=clean, selection=selection,
        )
    except (
        ArtifactError, FileNotFoundError, json.JSONDecodeError, OSError,
        subprocess.CalledProcessError, TypeError, ValueError,
    ) as error:
        print(json.dumps({
            "blockers": [f"preparation_error:{error}"],
            "ready_to_freeze": False,
        }, indent=2, sort_keys=True))
        return 2
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result.document, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps({
        "blockers": list(result.blockers),
        "draft_output": str(args.output) if args.output else None,
        "ready_to_freeze": result.ready_to_freeze,
        "validation_report_sha256": result.document["validation_report_sha256"],
    }, indent=2, sort_keys=True))
    return 0 if result.ready_to_freeze else 2


if __name__ == "__main__":
    raise SystemExit(main())
