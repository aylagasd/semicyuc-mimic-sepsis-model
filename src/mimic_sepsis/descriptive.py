"""Privacy-aware clinical and data-quality descriptive summaries."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math

import pandas as pd

from .feature_sources import LAB_ITEMS, VITAL_ITEMS
from .splits import patient_grouped_split


CLINICAL_CATEGORICAL_COLUMNS = (
    "gender", "race", "admission_type", "admission_location", "insurance",
    "first_careunit", "discharge_location",
)
SOFA_COMPONENTS = (
    "sofa_respiratory", "sofa_coagulation", "sofa_liver",
    "sofa_cardiovascular", "sofa_cns", "sofa_renal",
)


def _require(frame: pd.DataFrame, columns: set[str], name: str) -> None:
    missing = sorted(columns - set(frame.columns))
    if missing:
        raise ValueError(f"{name} is missing columns: {', '.join(missing)}")


def _safe_cell(value: int, minimum: int) -> bool:
    return value == 0 or value >= minimum


def prepare_descriptive_cohort(
    cohort: pd.DataFrame,
    sepsis_stays: pd.DataFrame,
    shock_stays: pd.DataFrame,
    *,
    split_config: Mapping,
    partitions: Sequence[str] = ("development", "validation"),
) -> pd.DataFrame:
    """Attach split and retrospective stay outcomes without returning test rows."""
    _require(
        cohort,
        {"subject_id", "hadm_id", "stay_id", "intime", "outtime", "age_at_icu"},
        "cohort",
    )
    _require(sepsis_stays, {"stay_id", "subject_id", "sepsis3"}, "sepsis_stays")
    _require(shock_stays, {"stay_id", "subject_id", "septic_shock"}, "shock_stays")
    if cohort["stay_id"].duplicated().any():
        raise ValueError("cohort must be unique by stay_id")
    allowed = tuple(partitions)
    if not allowed or not set(allowed).issubset({"development", "validation"}):
        raise ValueError("descriptive partitions must be development/validation")
    if split_config.get("group_key") != "subject_id":
        raise ValueError("split must be grouped by subject_id")
    source = cohort.copy()
    if "cohort_included" in source:
        source = source.loc[source["cohort_included"].fillna(False)].copy()
    split = patient_grouped_split(
        source,
        proportions=dict(split_config["proportions"]),
        seed=int(split_config["seed"]),
    )
    split = split.loc[split["partition"].isin(allowed)].copy()
    split["intime"] = pd.to_datetime(split["intime"], errors="coerce")
    split["outtime"] = pd.to_datetime(split["outtime"], errors="coerce")
    split["icu_los_days"] = (
        split["outtime"] - split["intime"]
    ).dt.total_seconds() / 86400
    if split["icu_los_days"].dropna().lt(0).any():
        raise ValueError("cohort contains negative ICU length of stay")
    if {"admittime", "dischtime"}.issubset(split.columns):
        split["hospital_los_days"] = (
            pd.to_datetime(split["dischtime"], errors="coerce")
            - pd.to_datetime(split["admittime"], errors="coerce")
        ).dt.total_seconds() / 86400
        if split["hospital_los_days"].dropna().lt(0).any():
            raise ValueError("cohort contains negative hospital length of stay")
    if "hospital_expire_flag" in split:
        split["hospital_mortality"] = pd.to_numeric(
            split["hospital_expire_flag"], errors="coerce"
        ).eq(1)

    sepsis_ids = set(
        sepsis_stays.loc[sepsis_stays["sepsis3"].fillna(False), "stay_id"]
    )
    shock_ids = set(
        shock_stays.loc[shock_stays["septic_shock"].fillna(False), "stay_id"]
    )
    if not shock_ids.issubset(sepsis_ids):
        raise ValueError("septic shock stays must be a subset of sepsis stays")
    split["sepsis3"] = split["stay_id"].isin(sepsis_ids)
    split["septic_shock"] = split["stay_id"].isin(shock_ids)
    return split.reset_index(drop=True)


def outcome_burden_summary(
    cohort: pd.DataFrame,
    *,
    privacy_minimum_cell: int = 10,
) -> pd.DataFrame:
    """Summarize cohort and endpoint burden with complementary suppression."""
    if privacy_minimum_cell <= 0:
        raise ValueError("privacy_minimum_cell must be positive")
    _require(
        cohort,
        {"subject_id", "hadm_id", "stay_id", "partition", "sepsis3", "septic_shock"},
        "cohort",
    )
    groups = [("overall", cohort)] + [
        (str(name), frame) for name, frame in cohort.groupby("partition", sort=True)
    ]
    rows = []
    for group_name, frame in groups:
        endpoints = ["sepsis3", "septic_shock"]
        if "hospital_mortality" in frame:
            endpoints.append("hospital_mortality")
        for endpoint in endpoints:
            positive = frame[endpoint].fillna(False)
            events = int(positive.sum())
            nonevents = int(len(frame) - events)
            event_patients = int(frame.loc[positive, "subject_id"].nunique())
            non_event_patients = int(frame.loc[~positive, "subject_id"].nunique())
            suppressed = not all(
                _safe_cell(value, privacy_minimum_cell)
                for value in (events, nonevents, event_patients, non_event_patients)
            )
            rows.append({
                "sample": group_name,
                "endpoint": endpoint,
                "privacy_suppressed": suppressed,
                "patients": pd.NA if suppressed else frame["subject_id"].nunique(),
                "admissions": pd.NA if suppressed else frame["hadm_id"].nunique(),
                "stays": pd.NA if suppressed else len(frame),
                "event_patients": pd.NA if suppressed else event_patients,
                "event_stays": pd.NA if suppressed else events,
                "stay_percent": float("nan") if suppressed or not len(frame) else 100 * events / len(frame),
            })
    result = pd.DataFrame(rows)
    for column in ("patients", "admissions", "stays", "event_patients", "event_stays"):
        result[column] = pd.array(result[column], dtype="Int64")
    return result


def continuous_descriptive_summary(
    cohort: pd.DataFrame,
    columns: Sequence[str] = ("age_at_icu", "icu_los_days"),
    *,
    privacy_minimum_cell: int = 10,
) -> pd.DataFrame:
    """Return median/IQR summaries overall, by partition, and by Sepsis-3."""
    selected = [column for column in columns if column in cohort]
    if "hospital_los_days" in cohort and "hospital_los_days" not in selected:
        selected.append("hospital_los_days")
    if not selected:
        raise ValueError("cohort has no requested continuous columns")
    _require(cohort, {"partition", "sepsis3", *selected}, "cohort")
    groups = [("overall", "all", cohort)]
    groups.extend(
        ("partition", str(name), frame)
        for name, frame in cohort.groupby("partition", sort=True)
    )
    groups.extend(
        ("sepsis3", str(bool(name)), frame)
        for name, frame in cohort.groupby("sepsis3", sort=True)
    )
    rows = []
    for stratum, level, frame in groups:
        for variable in selected:
            values = pd.to_numeric(frame[variable], errors="coerce").dropna()
            missing = int(frame[variable].isna().sum())
            suppressed = not all(
                _safe_cell(value, privacy_minimum_cell)
                for value in (len(values), missing)
            )
            rows.append({
                "stratum": stratum,
                "level": level,
                "variable": variable,
                "privacy_suppressed": suppressed,
                "n": pd.NA if suppressed else len(values),
                "missing": pd.NA if suppressed else missing,
                "median": float("nan") if suppressed or values.empty else values.median(),
                "q1": float("nan") if suppressed or values.empty else values.quantile(0.25),
                "q3": float("nan") if suppressed or values.empty else values.quantile(0.75),
            })
    result = pd.DataFrame(rows)
    result["n"] = pd.array(result["n"], dtype="Int64")
    result["missing"] = pd.array(result["missing"], dtype="Int64")
    return result


def categorical_descriptive_summary(
    cohort: pd.DataFrame,
    columns: Sequence[str] = CLINICAL_CATEGORICAL_COLUMNS,
    *,
    privacy_minimum_cell: int = 10,
) -> pd.DataFrame:
    """Return categorical counts with primary and complementary suppression."""
    selected = [column for column in columns if column in cohort]
    if not selected:
        raise ValueError("cohort has no requested categorical columns")
    _require(cohort, {"partition", *selected}, "cohort")
    groups = [("overall", cohort)] + [
        (str(name), frame) for name, frame in cohort.groupby("partition", sort=True)
    ]
    rows = []
    for sample, frame in groups:
        for variable in selected:
            values = frame[variable].astype("string").fillna("Missing")
            counts = values.value_counts(dropna=False).sort_index()
            primary = {
                str(level) for level, count in counts.items()
                if 0 < int(count) < privacy_minimum_cell
            }
            complementary: set[str] = set()
            if primary and len(counts) > len(primary):
                candidates = [
                    (int(count), str(level)) for level, count in counts.items()
                    if str(level) not in primary
                ]
                complementary.add(min(candidates)[1])
            for level, count in counts.items():
                label = str(level)
                suppressed = label in primary or label in complementary
                rows.append({
                    "sample": sample,
                    "variable": variable,
                    "level": label,
                    "privacy_suppressed": suppressed,
                    "complementary_suppressed": label in complementary,
                    "n": pd.NA if suppressed else int(count),
                    "denominator": pd.NA if suppressed else len(frame),
                    "percent": float("nan") if suppressed or not len(frame) else 100 * int(count) / len(frame),
                })
    result = pd.DataFrame(rows)
    result["n"] = pd.array(result["n"], dtype="Int64")
    result["denominator"] = pd.array(result["denominator"], dtype="Int64")
    return result


def partition_standardized_differences(
    cohort: pd.DataFrame,
    *,
    continuous_columns: Sequence[str] = ("age_at_icu", "icu_los_days"),
    categorical_columns: Sequence[str] = CLINICAL_CATEGORICAL_COLUMNS,
    privacy_minimum_cell: int = 10,
) -> pd.DataFrame:
    """Compare development and validation descriptively without p-values."""
    _require(cohort, {"partition"}, "cohort")
    left = cohort.loc[cohort["partition"].eq("development")]
    right = cohort.loc[cohort["partition"].eq("validation")]
    if left.empty or right.empty:
        raise ValueError("development and validation must both be present")
    rows = []
    selected_continuous = [column for column in continuous_columns if column in cohort]
    if "hospital_los_days" in cohort and "hospital_los_days" not in selected_continuous:
        selected_continuous.append("hospital_los_days")
    for variable in selected_continuous:
        first = pd.to_numeric(left[variable], errors="coerce").dropna()
        second = pd.to_numeric(right[variable], errors="coerce").dropna()
        suppressed = min(len(first), len(second)) < privacy_minimum_cell
        pooled = math.sqrt((first.var(ddof=1) + second.var(ddof=1)) / 2) if not suppressed else float("nan")
        smd = (
            0.0 if pooled == 0 and first.mean() == second.mean()
            else (first.mean() - second.mean()) / pooled
        ) if not suppressed and pd.notna(pooled) and pooled >= 0 else float("nan")
        rows.append({
            "variable": variable, "level": "continuous",
            "privacy_suppressed": suppressed, "standardized_difference": smd,
        })
    for variable in categorical_columns:
        if variable not in cohort:
            continue
        levels = sorted(set(
            cohort[variable].astype("string").fillna("Missing").astype(str)
        ))
        left_values = left[variable].astype("string").fillna("Missing").astype(str)
        right_values = right[variable].astype("string").fillna("Missing").astype(str)
        for level in levels:
            left_count = int(left_values.eq(level).sum())
            right_count = int(right_values.eq(level).sum())
            cells = (
                left_count, len(left) - left_count,
                right_count, len(right) - right_count,
            )
            suppressed = not all(_safe_cell(value, privacy_minimum_cell) for value in cells)
            p1, p2 = left_count / len(left), right_count / len(right)
            pooled = math.sqrt((p1 * (1 - p1) + p2 * (1 - p2)) / 2)
            smd = (
                0.0 if pooled == 0 and p1 == p2 else (p1 - p2) / pooled
            ) if not suppressed else float("nan")
            rows.append({
                "variable": variable, "level": level,
                "privacy_suppressed": suppressed, "standardized_difference": smd,
            })
    return pd.DataFrame(rows)


def outcome_timing_summary(
    cohort: pd.DataFrame,
    sepsis_stays: pd.DataFrame,
    shock_stays: pd.DataFrame,
    *,
    privacy_minimum_cell: int = 10,
) -> pd.DataFrame:
    """Summarize onset times relative to ICU admission for permitted partitions."""
    _require(cohort, {"stay_id", "intime", "partition"}, "cohort")
    specifications = (
        ("sepsis3", sepsis_stays, "t0", "sepsis3"),
        ("septic_shock", shock_stays, "shock_t0", "septic_shock"),
    )
    rows = []
    for endpoint, source, time_column, flag_column in specifications:
        _require(source, {"stay_id", time_column, flag_column}, endpoint)
        positive = source.loc[source[flag_column].fillna(False), ["stay_id", time_column]]
        positive = positive.drop_duplicates("stay_id", keep="first")
        joined = cohort[["stay_id", "intime", "partition"]].merge(
            positive, on="stay_id", how="inner", validate="one_to_one"
        )
        joined["hours_from_icu"] = (
            pd.to_datetime(joined[time_column]) - pd.to_datetime(joined["intime"])
        ).dt.total_seconds() / 3600
        groups = [("overall", joined)] + [
            (str(name), frame) for name, frame in joined.groupby("partition", sort=True)
        ]
        for sample, frame in groups:
            values = joined["hours_from_icu"] if sample == "overall" else frame["hours_from_icu"]
            values = values.dropna()
            suppressed = 0 < len(values) < privacy_minimum_cell
            rows.append({
                "sample": sample, "endpoint": endpoint,
                "privacy_suppressed": suppressed,
                "n": pd.NA if suppressed else len(values),
                "median_hours": float("nan") if suppressed or values.empty else values.median(),
                "q1_hours": float("nan") if suppressed or values.empty else values.quantile(0.25),
                "q3_hours": float("nan") if suppressed or values.empty else values.quantile(0.75),
            })
    result = pd.DataFrame(rows)
    result["n"] = pd.array(result["n"], dtype="Int64")
    return result


def feature_quality_summary(
    features: Mapping[str, pd.DataFrame],
    variables: Sequence[str],
    *,
    windows_hours: Sequence[int] = (6, 12, 24),
    privacy_minimum_cell: int = 10,
) -> pd.DataFrame:
    """Summarize measurement availability and density by split/window."""
    rows = []
    for partition, frame in features.items():
        _require(frame, {"subject_id", "stay_id"}, f"features[{partition}]")
        for variable in variables:
            for window in windows_hours:
                count_column = f"{variable}_count_{window}h"
                missing_column = f"{variable}_missing_{window}h"
                _require(frame, {count_column, missing_column}, f"features[{partition}]")
                counts = pd.to_numeric(frame[count_column], errors="coerce").fillna(0)
                missing = frame[missing_column].fillna(True).astype(bool)
                observed = ~missing
                protected = (
                    int(observed.sum()), int(missing.sum()),
                    int(frame.loc[observed, "subject_id"].nunique()),
                    int(frame.loc[missing, "subject_id"].nunique()),
                )
                suppressed = not all(
                    _safe_cell(value, privacy_minimum_cell) for value in protected
                )
                rows.append({
                    "partition": str(partition), "variable": variable,
                    "window_hours": int(window), "privacy_suppressed": suppressed,
                    "landmarks": pd.NA if suppressed else len(frame),
                    "patients": pd.NA if suppressed else frame["subject_id"].nunique(),
                    "observed_landmarks": pd.NA if suppressed else int(observed.sum()),
                    "percent_observed": float("nan") if suppressed or not len(frame) else 100 * observed.mean(),
                    "measurements": pd.NA if suppressed else int(counts.sum()),
                    "median_measurements": float("nan") if suppressed else counts.median(),
                    "p95_measurements": float("nan") if suppressed else counts.quantile(0.95),
                })
    result = pd.DataFrame(rows)
    for column in ("landmarks", "patients", "observed_landmarks", "measurements"):
        result[column] = pd.array(result[column], dtype="Int64")
    return result


def feature_source_quality_summary(
    chartevents: pd.DataFrame,
    labevents: pd.DataFrame,
    cohort: pd.DataFrame,
    *,
    privacy_minimum_cell: int = 10,
) -> pd.DataFrame:
    """Audit candidate, rejected, and accepted predictor-source events."""
    if privacy_minimum_cell <= 0:
        raise ValueError("privacy_minimum_cell must be positive")
    _require(chartevents, {"stay_id", "itemid", "charttime", "valuenum"}, "chartevents")
    _require(
        labevents,
        {"subject_id", "hadm_id", "itemid", "charttime", "storetime", "valuenum"},
        "labevents",
    )
    _require(cohort, {"subject_id", "hadm_id", "stay_id", "intime", "outtime"}, "cohort")
    rows: list[dict[str, object]] = []

    vitals = chartevents.loc[chartevents["itemid"].isin(VITAL_ITEMS)].copy()
    vitals["event_time"] = pd.to_datetime(vitals["charttime"], errors="coerce")
    vitals["numeric"] = pd.to_numeric(vitals["valuenum"], errors="coerce")
    vitals["variable"] = vitals["itemid"].map(
        lambda item: VITAL_ITEMS[int(item)][0]
    ).replace({"temperature_f": "temperature"})
    vital_valid = pd.Series(False, index=vitals.index)
    for itemid, (_, lower, upper) in VITAL_ITEMS.items():
        vital_valid |= vitals["itemid"].eq(itemid) & vitals["numeric"].between(
            lower, upper
        )
    vitals["valid_value"] = vital_valid
    for variable, frame in vitals.groupby("variable", sort=True):
        counts = {
            "candidates": len(frame),
            "missing_event_time": int(frame["event_time"].isna().sum()),
            "missing_value": int(frame["numeric"].isna().sum()),
            "outside_bounds": int((frame["numeric"].notna() & ~frame["valid_value"]).sum()),
            "stored_before_specimen": 0,
            "outside_icu_stay": 0,
            "accepted": int((frame["event_time"].notna() & frame["valid_value"]).sum()),
        }
        suppressed = any(
            0 < value < privacy_minimum_cell for value in counts.values()
        )
        rows.append({
            "source": "chartevents", "variable": str(variable),
            "privacy_suppressed": suppressed,
            **{key: pd.NA if suppressed else value for key, value in counts.items()},
        })

    labs = labevents.loc[labevents["itemid"].isin(LAB_ITEMS)].copy()
    labs["_source_row"] = range(len(labs))
    labs["specimen_time"] = pd.to_datetime(labs["charttime"], errors="coerce")
    labs["event_time"] = pd.to_datetime(labs["storetime"], errors="coerce")
    labs["numeric"] = pd.to_numeric(labs["valuenum"], errors="coerce")
    labs["variable"] = labs["itemid"].map(lambda item: LAB_ITEMS[int(item)][0])
    lab_valid = pd.Series(False, index=labs.index)
    for itemid, (_, lower, upper) in LAB_ITEMS.items():
        lab_valid |= labs["itemid"].eq(itemid) & labs["numeric"].between(
            lower, upper
        )
    labs["valid_value"] = lab_valid
    stays = cohort[["subject_id", "hadm_id", "stay_id", "intime", "outtime"]].copy()
    stays["intime"] = pd.to_datetime(stays["intime"], errors="coerce")
    stays["outtime"] = pd.to_datetime(stays["outtime"], errors="coerce")
    linked = labs.merge(stays, on=["subject_id", "hadm_id"], how="left")
    linked = linked.loc[
        linked["specimen_time"].ge(linked["intime"])
        & linked["specimen_time"].lt(linked["outtime"])
    ]
    linked_rows = set(linked["_source_row"])
    labs["linked_to_icu"] = labs["_source_row"].isin(linked_rows)
    labs["chronology_valid"] = labs["event_time"].ge(labs["specimen_time"])
    for variable, frame in labs.groupby("variable", sort=True):
        accepted = (
            frame["specimen_time"].notna()
            & frame["event_time"].notna()
            & frame["chronology_valid"]
            & frame["valid_value"]
            & frame["linked_to_icu"]
        )
        counts = {
            "candidates": len(frame),
            "missing_event_time": int(frame["event_time"].isna().sum()),
            "missing_value": int(frame["numeric"].isna().sum()),
            "outside_bounds": int((frame["numeric"].notna() & ~frame["valid_value"]).sum()),
            "stored_before_specimen": int((
                frame["event_time"].notna()
                & frame["specimen_time"].notna()
                & ~frame["chronology_valid"]
            ).sum()),
            "outside_icu_stay": int((
                frame["specimen_time"].notna() & ~frame["linked_to_icu"]
            ).sum()),
            "accepted": int(accepted.sum()),
        }
        suppressed = any(
            0 < value < privacy_minimum_cell for value in counts.values()
        )
        rows.append({
            "source": "labevents", "variable": str(variable),
            "privacy_suppressed": suppressed,
            **{key: pd.NA if suppressed else value for key, value in counts.items()},
        })
    result = pd.DataFrame(rows)
    count_columns = (
        "candidates", "missing_event_time", "missing_value", "outside_bounds",
        "stored_before_specimen", "outside_icu_stay", "accepted",
    )
    for column in count_columns:
        result[column] = pd.array(result[column], dtype="Int64")
    return result


def feature_value_summary(
    features: Mapping[str, pd.DataFrame],
    variables: Sequence[str],
    *,
    window_hours: int = 24,
    privacy_minimum_cell: int = 10,
) -> pd.DataFrame:
    """Return aggregate distributions of last observed predictor values."""
    rows = []
    for partition, frame in features.items():
        _require(frame, {"subject_id"}, f"features[{partition}]")
        for variable in variables:
            column = f"{variable}_last_{window_hours}h"
            _require(frame, {column}, f"features[{partition}]")
            numeric = pd.to_numeric(frame[column], errors="coerce")
            observed = numeric.notna()
            observed_patients = frame.loc[observed, "subject_id"].nunique()
            suppressed = (
                0 < int(observed.sum()) < privacy_minimum_cell
                or 0 < int(observed_patients) < privacy_minimum_cell
            )
            values = numeric.loc[observed]
            rows.append({
                "partition": str(partition), "variable": variable,
                "window_hours": int(window_hours), "privacy_suppressed": suppressed,
                "n": pd.NA if suppressed else len(values),
                "patients": pd.NA if suppressed else observed_patients,
                "median": float("nan") if suppressed or values.empty else values.median(),
                "q1": float("nan") if suppressed or values.empty else values.quantile(0.25),
                "q3": float("nan") if suppressed or values.empty else values.quantile(0.75),
                "minimum": float("nan") if suppressed or values.empty else values.min(),
                "maximum": float("nan") if suppressed or values.empty else values.max(),
            })
    result = pd.DataFrame(rows)
    result["n"] = pd.array(result["n"], dtype="Int64")
    result["patients"] = pd.array(result["patients"], dtype="Int64")
    return result


def sofa_completeness_summary(
    sofa_hourly: pd.DataFrame,
    cohort: pd.DataFrame,
    *,
    privacy_minimum_cell: int = 10,
) -> pd.DataFrame:
    """Summarize observed hourly SOFA components by permitted partition."""
    _require(sofa_hourly, {"stay_id", *SOFA_COMPONENTS}, "sofa_hourly")
    _require(cohort, {"stay_id", "subject_id", "partition"}, "cohort")
    source = sofa_hourly[["stay_id", *SOFA_COMPONENTS]].merge(
        cohort[["stay_id", "subject_id", "partition"]],
        on="stay_id", how="inner", validate="many_to_one",
    )
    rows = []
    for partition, frame in source.groupby("partition", sort=True):
        for component in SOFA_COMPONENTS:
            observed = frame[component].notna()
            protected = (
                int(observed.sum()), int((~observed).sum()),
                int(frame.loc[observed, "subject_id"].nunique()),
            )
            suppressed = not all(
                _safe_cell(value, privacy_minimum_cell) for value in protected
            )
            rows.append({
                "partition": str(partition), "component": component,
                "privacy_suppressed": suppressed,
                "hours": pd.NA if suppressed else len(frame),
                "observed_hours": pd.NA if suppressed else int(observed.sum()),
                "percent_observed": float("nan") if suppressed or not len(frame) else 100 * observed.mean(),
            })
    result = pd.DataFrame(rows)
    result["hours"] = pd.array(result["hours"], dtype="Int64")
    result["observed_hours"] = pd.array(result["observed_hours"], dtype="Int64")
    return result
