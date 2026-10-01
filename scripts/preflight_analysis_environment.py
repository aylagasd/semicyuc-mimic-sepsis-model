#!/usr/bin/env python3
"""Validate Python, Jupyter, R, and ggplot2 before running notebooks."""

from __future__ import annotations

import json

from mimic_sepsis.analysis_environment import inspect_analysis_environment


def main() -> int:
    report = inspect_analysis_environment()
    print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    return 0 if report.ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
