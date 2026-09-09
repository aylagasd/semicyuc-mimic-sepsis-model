import pandas as pd
import pytest

from mimic_sepsis.sepsis_labels import (
    build_sepsis_episodes,
    first_sepsis_episode_per_stay,
)


TSI = pd.Timestamp("2100-01-03 00:00")


def _pairs(**overrides):
    values = {
        "subject_id": [1], "hadm_id": [10], "antibiotic_id": [100],
        "culture_id": [200], "antibiotic_time": [TSI],
        "culture_time": [TSI + pd.Timedelta(hours=6)], "t_si": [TSI],
    }
    values.update(overrides)
    return pd.DataFrame(values)


def _stays(**overrides):
    values = {
        "subject_id": [1], "hadm_id": [10], "stay_id": [1000],
        "intime": [TSI - pd.Timedelta(hours=72)],
        "outtime": [TSI + pd.Timedelta(hours=48)],
    }
    values.update(overrides)
    return pd.DataFrame(values)


def _sofa(times, scores, stay_id=1000, missing=None):
    if missing is None:
        missing = [0] * len(times)
    return pd.DataFrame({
        "stay_id": [stay_id] * len(times), "endtime": times,
        "sofa_total": scores, "missing_components": missing,
    })


def test_baseline_and_acute_boundaries_and_first_crossing():
    sofa = _sofa(
        [TSI - pd.Timedelta(hours=48), TSI - pd.Timedelta(hours=1), TSI,
         TSI + pd.Timedelta(hours=1), TSI + pd.Timedelta(hours=24)],
        [4, 1, 2, 3, 8],
    )
    result = build_sepsis_episodes(_pairs(), _stays(), sofa).iloc[0]
    assert result.baseline_sofa == 1
    assert result.baseline_hour_count == 2
    assert result.acute_hour_count == 4
    assert result.t0 == TSI + pd.Timedelta(hours=1)
    assert result.peak_acute_time == TSI + pd.Timedelta(hours=24)


def test_absent_baseline_is_assumed_zero_and_marked():
    result = build_sepsis_episodes(
        _pairs(), _stays(), _sofa([TSI], [2], missing=[4])
    ).iloc[0]
    assert result.baseline_sofa == 0
    assert result.baseline_assumed_zero
    assert result.sepsis3
    assert result.missing_components_at_t0 == 4


def test_acute_lower_boundary_is_included():
    lower = TSI - pd.Timedelta(hours=24)
    result = build_sepsis_episodes(
        _pairs(), _stays(),
        _sofa([TSI - pd.Timedelta(hours=48), lower], [0, 2]),
    ).iloc[0]
    assert result.acute_hour_count == 1
    assert result.t0 == lower


def test_delta_below_two_does_not_qualify():
    result = build_sepsis_episodes(
        _pairs(), _stays(), _sofa([TSI - pd.Timedelta(hours=1), TSI], [3, 4])
    ).iloc[0]
    assert not result.sepsis3
    assert pd.isna(result.t0)
    assert pd.isna(result.label_available_at)


def test_label_availability_waits_for_second_infection_event():
    result = build_sepsis_episodes(
        _pairs(), _stays(), _sofa([TSI], [2])
    ).iloc[0]
    assert result.t0 == TSI
    assert result.t_si_confirmed_at == TSI + pd.Timedelta(hours=6)
    assert result.label_available_at == result.t_si_confirmed_at


def test_pair_is_evaluated_in_each_overlapping_stay():
    stays = _stays(
        subject_id=[1, 1], hadm_id=[10, 10], stay_id=[1000, 1001],
        intime=[TSI - pd.Timedelta(hours=2), TSI + pd.Timedelta(hours=2)],
        outtime=[TSI + pd.Timedelta(hours=1), TSI + pd.Timedelta(hours=12)],
    )
    sofa = pd.concat([_sofa([TSI], [2]), _sofa([TSI + pd.Timedelta(hours=3)], [3], 1001)])
    result = build_sepsis_episodes(_pairs(), stays, sofa)
    assert result["stay_id"].tolist() == [1000, 1001]


def test_nonoverlapping_pair_is_retained_with_reason():
    stays = _stays(intime=[TSI + pd.Timedelta(hours=25)], outtime=[TSI + pd.Timedelta(hours=30)])
    result = build_sepsis_episodes(_pairs(), stays, _sofa([], [])).iloc[0]
    assert result.exclusion_reason == "no_overlapping_icu_stay"
    assert pd.isna(result.stay_id)


def test_overlap_without_sofa_is_not_evaluable():
    result = build_sepsis_episodes(_pairs(), _stays(), _sofa([], [])).iloc[0]
    assert result.exclusion_reason == "no_acute_sofa_hours"
    assert not result.sepsis3


def test_full_window_coverage_is_audited_separately():
    full = _sofa([TSI - pd.Timedelta(hours=24), TSI, TSI + pd.Timedelta(hours=24)], [0, 2, 2])
    partial = _sofa([TSI, TSI + pd.Timedelta(hours=23)], [2, 2])
    assert build_sepsis_episodes(_pairs(), _stays(), full).iloc[0].acute_window_covered
    assert not build_sepsis_episodes(_pairs(), _stays(), partial).iloc[0].acute_window_covered


def test_first_episode_per_stay_uses_earliest_t0():
    pairs = pd.concat([
        _pairs(),
        _pairs(antibiotic_id=[101], culture_id=[201],
               antibiotic_time=[TSI + pd.Timedelta(hours=1)],
               culture_time=[TSI + pd.Timedelta(hours=2)],
               t_si=[TSI + pd.Timedelta(hours=1)]),
    ], ignore_index=True)
    sofa = _sofa([TSI, TSI + pd.Timedelta(hours=1)], [2, 4])
    episodes = build_sepsis_episodes(pairs, _stays(), sofa)
    selected = first_sepsis_episode_per_stay(episodes)
    assert len(selected) == 1
    assert selected.iloc[0].antibiotic_id == 100


def test_duplicate_pair_source_ids_are_rejected():
    with pytest.raises(ValueError, match="unique"):
        build_sepsis_episodes(pd.concat([_pairs(), _pairs()]), _stays(), _sofa([TSI], [2]))


def test_invalid_configuration_is_rejected():
    with pytest.raises(ValueError, match="windows"):
        build_sepsis_episodes(_pairs(), _stays(), _sofa([TSI], [2]), acute_hours_after=-1)
