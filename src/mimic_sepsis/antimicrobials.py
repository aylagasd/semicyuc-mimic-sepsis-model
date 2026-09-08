"""Versioned antimicrobial classification and EMAR confirmation."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


EXCLUDED_ROUTE_CODES = {"OU", "OS", "OD", "AU", "AS", "AD", "TP"}
EXCLUDED_DRUG_TERMS = ("cream", "desensitization", "ophth", "gel", "ointment", "powder")
ADMINISTRATION_EVENTS = ("administered", "started", "restarted")


def load_antimicrobial_rules(path: Path) -> pd.DataFrame:
    """Load and validate the ordered antimicrobial substring rules."""
    rules = pd.read_csv(path, dtype="string")
    if list(rules.columns) != ["pattern", "group"] or rules.empty:
        raise ValueError("Rules must contain non-empty pattern and group columns")
    if rules.isna().any().any() or rules["pattern"].duplicated().any():
        raise ValueError("Rules contain missing or duplicate patterns")
    rules["pattern"] = rules["pattern"].str.lower()
    return rules


def classify_prescriptions(
    prescriptions: pd.DataFrame, rules: pd.DataFrame
) -> pd.DataFrame:
    """Classify prescription rows while retaining an auditable reason."""
    required = {"pharmacy_id", "drug", "route", "drug_type", "starttime"}
    missing = sorted(required - set(prescriptions.columns))
    if missing:
        raise ValueError(f"prescriptions is missing columns: {', '.join(missing)}")
    result = prescriptions.copy()
    drug = result["drug"].fillna("").astype(str).str.lower()
    route = result["route"].fillna("").astype(str)
    result["matched_pattern"] = pd.Series(pd.NA, index=result.index, dtype="string")
    result["antimicrobial_group"] = pd.Series(pd.NA, index=result.index, dtype="string")
    for rule in rules.itertuples(index=False):
        unmatched = result["matched_pattern"].isna()
        matched = drug.str.contains(rule.pattern, regex=False)
        result.loc[unmatched & matched, "matched_pattern"] = rule.pattern
        result.loc[unmatched & matched, "antimicrobial_group"] = rule.group

    result["classification_reason"] = "included"
    result.loc[result["matched_pattern"].isna(), "classification_reason"] = "no_rule_match"
    result.loc[result["drug_type"].eq("BASE"), "classification_reason"] = "base_product"
    excluded_route = (
        route.str.upper().isin(EXCLUDED_ROUTE_CODES)
        | route.str.lower().str.contains("eye|ear|topical", regex=True)
    )
    result.loc[excluded_route, "classification_reason"] = "excluded_route"
    excluded_form = drug.apply(lambda value: any(term in value for term in EXCLUDED_DRUG_TERMS))
    result.loc[excluded_form, "classification_reason"] = "excluded_form"
    result["is_antimicrobial"] = result["classification_reason"].eq("included")
    result["prescription_time"] = pd.to_datetime(result["starttime"], errors="coerce")
    result.loc[result["prescription_time"].isna(), "classification_reason"] = "missing_starttime"
    result.loc[result["prescription_time"].isna(), "is_antimicrobial"] = False
    return result


def confirm_administrations(
    classified_prescriptions: pd.DataFrame, emar: pd.DataFrame
) -> pd.DataFrame:
    """Return earliest qualifying EMAR administration per antimicrobial order."""
    required_rx = {"subject_id", "hadm_id", "pharmacy_id", "is_antimicrobial"}
    required_emar = {"subject_id", "hadm_id", "pharmacy_id", "charttime", "event_txt"}
    for frame, required, name in [
        (classified_prescriptions, required_rx, "classified_prescriptions"),
        (emar, required_emar, "emar"),
    ]:
        missing = sorted(required - set(frame.columns))
        if missing:
            raise ValueError(f"{name} is missing columns: {', '.join(missing)}")
    administrations = emar.copy()
    event = administrations["event_txt"].fillna("").str.lower()
    qualifying = event.apply(
        lambda value: any(marker in value for marker in ADMINISTRATION_EVENTS)
    )
    administrations = administrations.loc[qualifying].copy()
    administrations["administration_time"] = pd.to_datetime(
        administrations["charttime"], errors="coerce"
    )
    administrations = administrations.dropna(subset=["pharmacy_id", "administration_time"])
    administrations = (
        administrations.sort_values("administration_time")
        .drop_duplicates(["subject_id", "hadm_id", "pharmacy_id"], keep="first")
    )
    eligible = classified_prescriptions.loc[classified_prescriptions["is_antimicrobial"]].copy()
    return eligible.merge(
        administrations[["subject_id", "hadm_id", "pharmacy_id", "administration_time", "event_txt"]],
        on=["subject_id", "hadm_id", "pharmacy_id"], how="left", validate="many_to_one",
    )
