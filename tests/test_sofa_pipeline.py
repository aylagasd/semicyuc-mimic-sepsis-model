import pandas as pd
import pytest

from mimic_sepsis.sofa_pipeline import COMPONENTS, assemble_hourly_sofa, rolling_interval_worst_score
from mimic_sepsis.sofa_demo import build_demo_hourly_sofa


def test_interval_overlap_is_leakage_safe_and_left_open():
    grid = pd.DataFrame({"stay_id":[1], "hr":[0], "endtime":["2100-01-02"]})
    intervals = pd.DataFrame({
        "stay_id":[1,1,1], "starttime":["2100-01-01","2100-01-01 12:00","2100-01-02 00:01"],
        "endtime":["2100-01-01 00:00","2100-01-01 13:00","2100-01-02 01:00"], "score":[4,3,4],
    })
    assert rolling_interval_worst_score(grid, intervals).loc[0,"score_24h"] == 3


def test_assemble_preserves_missingness_and_mimic_total():
    grid = pd.DataFrame({"subject_id":[1],"hadm_id":[10],"stay_id":[100],"hr":[0],"endtime":["2100-01-01"]})
    tables = {}
    for index, name in enumerate(COMPONENTS):
        score = pd.NA if name == "liver" else index % 3
        tables[name] = pd.DataFrame({"stay_id":[100],"hr":[0],"score_24h":pd.array([score],dtype="Int64")})
    result = assemble_hourly_sofa(grid,tables)
    assert result.loc[0,"missing_components"] == 1
    assert pd.isna(result.loc[0,"sofa_complete"])
    assert result.loc[0,"sofa_total"] == 4


def test_assemble_requires_every_component():
    with pytest.raises(ValueError, match="Missing SOFA"):
        assemble_hourly_sofa(pd.DataFrame(), {})


def test_demo_pipeline_handles_stay_without_vasoactive_intervals():
    stays = pd.DataFrame({
        "subject_id":[1], "hadm_id":[10], "stay_id":[100],
        "intime":["2100-01-01"], "outtime":["2100-01-01 02:00"],
    })
    chart = pd.DataFrame({
        "stay_id":[100,100], "itemid":[220045,220045],
        "charttime":["2100-01-01","2100-01-01 01:00"],
        "value":["80","80"], "valuenum":[80,80],
    })
    labs = pd.DataFrame(columns=["subject_id","hadm_id","itemid","charttime","valuenum","valueuom"])
    inputs = pd.DataFrame(columns=["stay_id","starttime","endtime","itemid","rate","rateuom"])
    outputs = pd.DataFrame(columns=["stay_id","itemid","charttime","value"])
    procedures = pd.DataFrame(columns=["stay_id","itemid","starttime","endtime"])
    result = build_demo_hourly_sofa(
        icustays=stays, chartevents=chart, labevents=labs,
        inputevents=inputs, outputevents=outputs, procedureevents=procedures,
    )
    assert not result.empty
    assert result["sofa_cardiovascular"].isna().all()
