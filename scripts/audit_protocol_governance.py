#!/usr/bin/env python3
"""Audit agreement between protocol status, decision register, and dossier."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mimic_sepsis.protocol_governance import audit_protocol_governance


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--protocol-status", type=Path, default=Path("config/protocol_status.json")
    )
    parser.add_argument(
        "--decision-register", type=Path, default=Path("docs/decision_register.md")
    )
    parser.add_argument(
        "--clinical-dossier", type=Path,
        default=Path("docs/clinical_freeze_dossier.md"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        protocol = json.loads(args.protocol_status.read_text(encoding="utf-8"))
        audit = audit_protocol_governance(
            protocol,
            args.decision_register.read_text(encoding="utf-8"),
            args.clinical_dossier.read_text(encoding="utf-8"),
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({
            "error": "protocol_governance_audit_failed",
            "error_type": type(error).__name__,
            "ready": False,
        }, indent=2, sort_keys=True))
        return 2
    print(json.dumps(audit.to_dict(), indent=2, sort_keys=True))
    return 0 if audit.ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
