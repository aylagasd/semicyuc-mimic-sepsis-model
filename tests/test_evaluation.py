import numpy as np
import pandas as pd
import pytest

from mimic_sepsis.evaluation import (
    patient_cluster_bootstrap_comparison,
    percentile_intervals,
)


def _table():
    return pd.DataFrame({
        "subject_id": np.repeat(np.arange(10), 2),
        "outcome": np.tile([0, 1], 10),
    })


def test_identical_models_have_zero_paired_differences():
    table = _table()
    probability = np.tile([0.2, 0.8], 10)
    result = patient_cluster_bootstrap_comparison(
        table, probability, probability, replicates=25, seed=3
    )
    assert (result.filter(like="delta_") == 0).all(axis=None)


def test_bootstrap_is_reproducible_and_retains_requested_replicates():
    table = _table()
    reference = np.repeat(0.5, len(table))
    candidate = np.tile([0.1, 0.9], 10)
    first = patient_cluster_bootstrap_comparison(
        table, reference, candidate, replicates=20, seed=7
    )
    second = patient_cluster_bootstrap_comparison(
        table, reference, candidate, replicates=20, seed=7
    )
    pd.testing.assert_frame_equal(first, second)
    assert len(first) == 20


def test_percentile_intervals_count_only_finite_estimates():
    bootstrap = pd.DataFrame({"replicate": [1, 2, 3], "delta_auroc": [0.1, np.nan, 0.3]})
    result = percentile_intervals(bootstrap, confidence_level=0.8).iloc[0]
    assert result.successful_replicates == 2
    assert result.lower == pytest.approx(0.12)
    assert result.upper == pytest.approx(0.28)


def test_invalid_probability_alignment_fails():
    with pytest.raises(ValueError, match="align"):
        patient_cluster_bootstrap_comparison(_table(), [0.5], [0.5], replicates=2)
