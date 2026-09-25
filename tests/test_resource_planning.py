from types import SimpleNamespace

import pandas as pd
import pytest

from mimic_sepsis.resource_planning import audit_pretest_memory


def _bundle():
    return SimpleNamespace(
        cohort=pd.DataFrame({"subject_id": [1, 2]}),
        landmarks={
            "development": pd.DataFrame({"subject_id": [1], "outcome": [0]}),
            "validation": pd.DataFrame({"subject_id": [2], "outcome": [1]}),
        },
        features={
            "development": pd.DataFrame({"subject_id": [1], "x": [1.0]}),
            "validation": pd.DataFrame({"subject_id": [2], "x": [2.0]}),
        },
    )


def test_memory_audit_is_aggregate_and_budgeted(monkeypatch):
    monkeypatch.setattr(
        "mimic_sepsis.resource_planning.available_memory_bytes", lambda: 12345
    )
    result = audit_pretest_memory(
        _bundle(), target_ram_gib=1, maximum_ram_fraction=0.5,
        working_set_multiplier=2, fixed_overhead_gib=0,
    )
    assert result.rows == 6
    assert result.columns_loaded == 9
    assert result.estimated_peak_bytes == 2 * result.input_bytes
    assert result.current_available_bytes == 12345
    assert result.ready_for_target
    assert "subject_id" not in result.to_dict()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"target_ram_gib": 0},
        {"maximum_ram_fraction": 1},
        {"working_set_multiplier": 0.5},
        {"fixed_overhead_gib": -1},
    ],
)
def test_memory_audit_rejects_invalid_profile(kwargs):
    with pytest.raises(ValueError):
        audit_pretest_memory(_bundle(), **kwargs)
