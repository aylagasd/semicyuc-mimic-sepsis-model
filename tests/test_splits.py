import pandas as pd
import pytest

from mimic_sepsis.splits import assert_patient_isolation, patient_grouped_split


def rows():
    return pd.DataFrame({
        "subject_id": [patient for patient in range(20) for _ in range(3)],
        "landmark": range(60),
    })


def test_all_rows_of_patient_share_partition():
    result = patient_grouped_split(rows())
    assert result.groupby("subject_id")["partition"].nunique().max() == 1
    assert result.groupby("partition")["subject_id"].nunique().to_dict() == {
        "development": 14, "test": 3, "validation": 3,
    }


def test_split_is_reproducible_and_seeded():
    first = patient_grouped_split(rows(), seed=7)
    second = patient_grouped_split(rows(), seed=7)
    third = patient_grouped_split(rows(), seed=8)
    pd.testing.assert_series_equal(first["partition"], second["partition"])
    assert not first["partition"].equals(third["partition"])


def test_row_order_does_not_change_patient_assignment():
    original = patient_grouped_split(rows(), seed=7).set_index("landmark")["partition"]
    shuffled = patient_grouped_split(rows().sample(frac=1, random_state=2), seed=7).set_index("landmark")["partition"]
    pd.testing.assert_series_equal(original.sort_index(), shuffled.sort_index())


def test_overlap_detector_rejects_patient_in_two_partitions():
    invalid = pd.DataFrame({"subject_id": [1, 1], "partition": ["development", "test"]})
    with pytest.raises(ValueError, match="multiple"):
        assert_patient_isolation(invalid)
