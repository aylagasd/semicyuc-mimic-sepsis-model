import numpy as np
import pandas as pd
import pytest

from mimic_sepsis.subgroups import attach_audit_subgroups, subgroup_performance


def test_attach_subgroups_derives_age_and_preserves_administrative_labels():
    table = pd.DataFrame({"stay_id": [10, 10, 20], "outcome": [0, 1, 0]})
    cohort = pd.DataFrame({
        "stay_id": [10, 20], "age_at_icu": [44, 80],
        "gender": ["F", None], "race": ["RECORDED A", "RECORDED B"],
    })
    result = attach_audit_subgroups(table, cohort)
    assert result["age_group"].tolist() == ["18-44", "18-44", "80+"]
    assert result["gender"].tolist() == ["F", "F", "Missing"]
    assert result["race"].tolist() == ["RECORDED A", "RECORDED A", "RECORDED B"]


def test_small_cells_suppress_counts_and_metrics():
    table = pd.DataFrame({
        "subject_id": range(6), "outcome": [1, 0, 0, 0, 0, 0],
        "group": ["small"] * 6,
    })
    result = subgroup_performance(
        table, np.repeat(0.2, 6), subgroup_columns=("group",),
        minimum_events=2, minimum_nonevents=2, privacy_minimum_cell=2,
    ).iloc[0]
    assert result.privacy_suppressed
    assert pd.isna(result.events) and pd.isna(result.landmarks)
    assert not result.metrics_reportable and np.isnan(result.auroc)


def test_small_cell_triggers_complementary_suppression():
    table = pd.DataFrame({
        "subject_id": range(24),
        "outcome": [1, 0, 0, 0] + [1, 0] * 10,
        "group": ["small"] * 4 + ["large"] * 20,
    })
    result = subgroup_performance(
        table, np.repeat(0.2, 24), subgroup_columns=("group",),
        minimum_events=2, minimum_nonevents=2, privacy_minimum_cell=2,
    ).set_index("level")
    assert result.loc["small", "privacy_suppressed"]
    assert not result.loc["small", "complementary_suppressed"]
    assert result.loc["large", "privacy_suppressed"]
    assert result.loc["large", "complementary_suppressed"]
    assert pd.isna(result.loc["large", "events"])


def test_metrics_require_prespecified_events_and_nonevents():
    table = pd.DataFrame({
        "subject_id": range(12), "outcome": [0, 1] * 6,
        "group": ["eligible"] * 12,
    })
    result = subgroup_performance(
        table, np.tile([0.2, 0.8], 6), subgroup_columns=("group",),
        minimum_events=5, minimum_nonevents=5, privacy_minimum_cell=2,
    ).iloc[0]
    assert result.metrics_reportable
    assert not result.complementary_suppressed
    assert result.events == 6 and result.nonevents == 6
    assert result.auroc == pytest.approx(1)


def test_duplicate_cohort_stays_fail_before_many_to_many_join():
    with pytest.raises(ValueError, match="unique"):
        attach_audit_subgroups(
            pd.DataFrame({"stay_id": [1]}),
            pd.DataFrame({"stay_id": [1, 1], "age_at_icu": [50, 51]}),
        )
