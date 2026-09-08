import pytest

from mimic_sepsis.sofa import (
    cardiovascular_score, cns_score, coagulation_score, liver_score,
    renal_score, respiratory_score, total_sofa,
)


@pytest.mark.parametrize("value,expected", [(400,0),(399,1),(299,2),(199,2)])
def test_respiratory_without_support(value, expected):
    assert respiratory_score(value, False) == expected


@pytest.mark.parametrize("value,expected", [(200,2),(199,3),(100,3),(99,4)])
def test_respiratory_with_support(value, expected):
    assert respiratory_score(value, True) == expected


@pytest.mark.parametrize("value,expected", [(150,0),(149,1),(99,2),(49,3),(19,4)])
def test_coagulation_boundaries(value, expected):
    assert coagulation_score(value) == expected


@pytest.mark.parametrize("value,expected", [(1.1,0),(1.2,1),(2,2),(6,3),(12,4)])
def test_liver_boundaries(value, expected):
    assert liver_score(value) == expected


def test_cardiovascular_uses_worst_therapy():
    assert cardiovascular_score(map_mmhg=80, norepinephrine=0.11) == 4
    assert cardiovascular_score(map_mmhg=65) == 1
    assert cardiovascular_score(map_mmhg=80, dobutamine=1) == 2


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        ({"dopamine": 5}, 2), ({"dopamine": 5.01}, 3),
        ({"dopamine": 15}, 3), ({"dopamine": 15.01}, 4),
        ({"norepinephrine": 0.1}, 3), ({"norepinephrine": 0.101}, 4),
    ],
)
def test_cardiovascular_dose_boundaries(kwargs, expected):
    assert cardiovascular_score(**kwargs) == expected


@pytest.mark.parametrize("value,expected", [(15,0),(14,1),(12,2),(9,3),(5,4)])
def test_cns_boundaries(value, expected):
    assert cns_score(value) == expected


def test_renal_takes_worse_of_creatinine_and_urine():
    assert renal_score(1.0, 100) == 4
    assert renal_score(3.5, 600) == 3
    assert renal_score(None, None) is None


@pytest.mark.parametrize(
    "creatinine,urine,expected",
    [(1.2, None, 1), (2, None, 2), (3.5, None, 3), (5, None, 4),
     (None, 500, 0), (None, 499, 3), (None, 200, 3), (None, 199, 4)],
)
def test_renal_boundaries(creatinine, urine, expected):
    assert renal_score(creatinine, urine) == expected


@pytest.mark.parametrize(
    "call",
    [
        lambda: respiratory_score(-1), lambda: coagulation_score(-1),
        lambda: liver_score(-1), lambda: cardiovascular_score(norepinephrine=-0.1),
        lambda: renal_score(-1, None), lambda: renal_score(None, -1),
    ],
)
def test_negative_values_are_rejected(call):
    with pytest.raises(ValueError, match="non-negative"):
        call()


def test_gcs_outside_scale_is_rejected():
    with pytest.raises(ValueError, match="between 3 and 15"):
        cns_score(16)


def test_respiratory_support_must_be_contemporaneous():
    scores = [respiratory_score(68, False), respiratory_score(120, True)]
    assert scores == [2, 3]
    assert max(scores) == 3


def test_total_requires_six_and_exposes_missing_assumption():
    assert total_sofa(1, 2, 0, 1, 0, None) is None
    assert total_sofa(1, 2, 0, 1, 0, None, mimic_missing_components_as_zero=True) == 4
    with pytest.raises(ValueError, match="six"):
        total_sofa(1, 2)
