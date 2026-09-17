#!/usr/bin/env python3
"""Check a PostgreSQL MIMIC installation without reading patient rows."""

from __future__ import annotations

import json

from mimic_sepsis.config import MIMICSettings
from mimic_sepsis.db import check_mimic_access, create_mimic_engine


def main() -> int:
    settings = MIMICSettings.from_env()
    engine = create_mimic_engine(settings)
    try:
        report = check_mimic_access(engine)
    finally:
        engine.dispose()
    # Never serialize settings, URL, username, hostname or credentials.
    print(json.dumps({
        "connected": report.connected,
        "ready": report.ready,
        "available_required_schemas": sorted(
            set(settings.schemas) & set(report.available_schemas)
        ),
        "missing_schemas": report.missing_schemas,
        "missing_tables": report.missing_tables,
        "read_only": True,
    }, indent=2, sort_keys=True))
    return 0 if report.ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
