"""End-to-end hourly SOFA assembly for the MIMIC-IV v2.2 demo."""

from __future__ import annotations

import pandas as pd

from .sofa import (
    cardiovascular_score, cns_score, coagulation_score, liver_score,
    renal_score, respiratory_score,
)
from .sofa_hourly import build_icustay_hourly_grid, rolling_worst_score
from .sofa_labs import link_labs_to_icu_stays, normalize_sofa_labs
from .sofa_neuro_cardio import (
    normalize_gcs_events, normalize_map_events, normalize_vasoactive_intervals,
    reconstruct_gcs,
)
from .sofa_pipeline import assemble_hourly_sofa, rolling_interval_worst_score
from .sofa_resp_renal import (
    add_contemporaneous_invasive_ventilation, pair_pao2_with_fio2,
    urine_output_at_landmarks,
)


def _rolling(grid: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    return rolling_worst_score(grid, events[["stay_id", "event_time", "score"]])


def _max_components(grid: pd.DataFrame, *tables: pd.DataFrame) -> pd.DataFrame:
    result = grid[["stay_id", "hr", "endtime"]].copy()
    columns = []
    for index, table in enumerate(tables):
        name = f"score_{index}"
        result = result.merge(
            table[["stay_id", "hr", "score_24h"]].rename(columns={"score_24h": name}),
            on=["stay_id", "hr"], how="left", validate="one_to_one",
        )
        columns.append(name)
    result["score_24h"] = result[columns].max(axis=1).astype("Int64")
    return result


def _link_pao2(labevents: pd.DataFrame, icustays: pd.DataFrame) -> pd.DataFrame:
    pao2 = labevents.loc[labevents["itemid"].eq(50821), [
        "subject_id", "hadm_id", "itemid", "charttime", "valuenum"
    ]].copy()
    pao2["charttime"] = pd.to_datetime(pao2["charttime"], errors="coerce")
    stays = icustays[["subject_id", "hadm_id", "stay_id", "intime", "outtime"]].copy()
    stays["intime"] = pd.to_datetime(stays["intime"], errors="coerce")
    stays["outtime"] = pd.to_datetime(stays["outtime"], errors="coerce")
    linked = pao2.merge(stays, on=["subject_id", "hadm_id"], how="inner")
    return linked.loc[
        linked["charttime"].ge(linked["intime"]) & linked["charttime"].lt(linked["outtime"]),
        ["stay_id", "itemid", "charttime", "valuenum"],
    ]


def build_demo_hourly_sofa(
    *, icustays: pd.DataFrame, chartevents: pd.DataFrame,
    labevents: pd.DataFrame, inputevents: pd.DataFrame,
    outputevents: pd.DataFrame, procedureevents: pd.DataFrame,
) -> pd.DataFrame:
    """Build an audited hourly SOFA table from raw demo dataframes."""
    grid = build_icustay_hourly_grid(icustays, chartevents)

    pao2 = _link_pao2(labevents, icustays)
    fio2 = chartevents[["stay_id", "itemid", "charttime", "valuenum"]]
    respiratory = pair_pao2_with_fio2(pao2, fio2)
    respiratory = add_contemporaneous_invasive_ventilation(respiratory, procedureevents)
    respiratory["event_time"] = respiratory["pao2_time"]
    respiratory["score"] = respiratory.apply(
        lambda row: respiratory_score(row.pao2_fio2, row.invasive_ventilation)
        if pd.notna(row.pao2_fio2) else None, axis=1,
    )
    respiratory_table = _rolling(grid, respiratory.dropna(subset=["score"]))

    labs = link_labs_to_icu_stays(normalize_sofa_labs(labevents), icustays)
    lab_tables = {}
    scorers = {"platelets": coagulation_score, "bilirubin": liver_score, "creatinine": renal_score}
    for component, scorer in scorers.items():
        events = labs.loc[labs["component"].eq(component), ["stay_id", "charttime", "value"]].copy()
        events["event_time"] = events["charttime"]
        events["score"] = events["value"].map(scorer)
        lab_tables[component] = _rolling(grid, events)

    gcs = reconstruct_gcs(
        chartevents[["stay_id", "charttime", "itemid", "value", "valuenum"]],
        contemporaneous_minutes=0,
    )
    gcs["event_time"] = gcs["charttime"]
    gcs["score"] = gcs["gcs_total"].map(cns_score)
    cns_table = _rolling(grid, gcs)

    map_events = normalize_map_events(chartevents[["stay_id", "charttime", "itemid", "valuenum"]])
    map_events["event_time"] = map_events["charttime"]
    map_events["score"] = map_events["map_mmhg"].map(lambda value: cardiovascular_score(map_mmhg=value))
    map_table = _rolling(grid, map_events)
    vaso = normalize_vasoactive_intervals(inputevents)
    if vaso.empty:
        vaso["score"] = pd.Series(dtype="Int64")
    else:
        vaso["score"] = vaso.apply(
            lambda row: cardiovascular_score(**{row.drug: row.dose_mcg_kg_min}), axis=1
        )
    vaso_table = rolling_interval_worst_score(grid, vaso)
    cardiovascular_table = _max_components(grid, map_table, vaso_table)

    landmarks = grid[["stay_id", "hr", "endtime"]].rename(columns={"endtime": "landmark_time"})
    urine_source = outputevents.rename(columns={"value": "value"})
    urine = urine_output_at_landmarks(urine_source, landmarks)
    urine["score_24h"] = urine["urine_output_ml"].map(lambda value: renal_score(None, value))
    urine = urine.rename(columns={"landmark_time": "endtime"})
    renal_table = _max_components(grid, lab_tables["creatinine"], urine)

    return assemble_hourly_sofa(grid, {
        "respiratory": respiratory_table,
        "coagulation": lab_tables["platelets"],
        "liver": lab_tables["bilirubin"],
        "cardiovascular": cardiovascular_table,
        "cns": cns_table,
        "renal": renal_table,
    })
