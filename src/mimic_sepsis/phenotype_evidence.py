"""Build a content-bound aggregate dossier for phenotype freeze review.

The report contains unsuppressed aggregate counts and therefore belongs in the
protected derived-data area, even though it contains no row identifiers.  It is
evidence for human review; it cannot mutate protocol status.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from .artifacts import ArtifactStore, ArtifactValidationError
from .chunked_labels import (
    COMPLETE_SOFA_ARTIFACTS,
    INFECTION_SENSITIVITY_ARTIFACTS,
    PRIMARY_LABEL_ARTIFACTS,
    SHOCK_SENSITIVITY_ARTIFACTS,
)
from .chunked_sofa import (
    partitioned_dataset_sha256,
    read_partitioned_dataset,
    validate_partitioned_dataset,
)
from .phenotype_audit import (
    coverage_sensitivity_summary,
    coverage_summary,
    complete_sofa_sensitivity_summary,
    decision_evidence_summary,
    infection_timing_summary,
    infection_evidence_sensitivity_summary,
    pair_multiplicity,
    phenotype_summary,
    shock_proxy_summary,
    shock_concurrency_sensitivity_summary,
    sofa_completeness_summary,
    unavailable_shock_concurrency_sensitivities,
    unavailable_complete_sofa_sensitivity,
    unavailable_infection_evidence_sensitivities,
)
from .protected_evidence import (
    protected_evidence_sha256,
    read_protected_evidence,
    write_protected_evidence,
)
from .sepsis_labels import first_sepsis_episode_per_stay


REPORT_TABLES = (
    "phenotype_summary",
    "infection_timing",
    "infection_evidence_sensitivities",
    "pair_multiplicity",
    "coverage",
    "coverage_sensitivities",
    "complete_sofa_sensitivities",
    "sofa_completeness_at_t0",
    "shock_proxy",
    "shock_concurrency_sensitivities",
    "decision_evidence",
)
FORBIDDEN_REPORT_COLUMNS = frozenset({
    "subject_id", "hadm_id", "stay_id", "antibiotic_id", "culture_id",
})


@dataclass(frozen=True)
class ValidatedPhenotypeSource:
    """Validated patient-level inputs plus non-sensitive source provenance."""

    layout: str
    data_version: str
    config_sha256: str
    artifact_sha256: Mapping[str, str]
    tables: Mapping[str, pd.DataFrame]


def _same(values: list[str], field: str) -> str:
    unique = set(values)
    if len(unique) != 1:
        raise ArtifactValidationError(f"Label artifacts disagree on {field}")
    return unique.pop()


def _demo_label_directory(path: Path) -> Path | None:
    direct = path if path.name == "40_labels" else path / "40_labels"
    expected = direct / "sepsis_episodes.manifest.json"
    return direct if expected.is_file() else None


def load_validated_phenotype_source(path: str | Path) -> ValidatedPhenotypeSource:
    """Load either a demo run or a partitioned full-pipeline label run."""
    root = Path(path)
    demo = _demo_label_directory(root)
    if demo is not None:
        store = ArtifactStore(demo)
        optional_present = [
            (demo / f"{name}.manifest.json").is_file()
            for name in COMPLETE_SOFA_ARTIFACTS
        ]
        if any(optional_present) and not all(optional_present):
            raise ArtifactValidationError(
                "Complete-SOFA sensitivity artifacts are incomplete"
            )
        shock_sensitivity_present = all(
            (demo / f"{name}.manifest.json").is_file()
            for name in SHOCK_SENSITIVITY_ARTIFACTS
        )
        infection_optional_present = [
            (demo / f"{name}.manifest.json").is_file()
            for name in INFECTION_SENSITIVITY_ARTIFACTS
        ]
        if any(infection_optional_present) and not all(infection_optional_present):
            raise ArtifactValidationError(
                "Infection sensitivity artifacts are incomplete"
            )
        names = PRIMARY_LABEL_ARTIFACTS + (
            COMPLETE_SOFA_ARTIFACTS if all(optional_present) else ()
        ) + (SHOCK_SENSITIVITY_ARTIFACTS if shock_sensitivity_present else ()) + (
            INFECTION_SENSITIVITY_ARTIFACTS
            if all(infection_optional_present)
            else ()
        )
        manifests = {name: store.validate(name) for name in names}
        data_version = _same(
            [item.data_version for item in manifests.values()], "data_version"
        )
        config_sha256 = _same(
            [item.config_sha256 for item in manifests.values()], "config_sha256"
        )
        tables = {
            name: store.read_dataframe(name, validate=False)
            for name in names
        }
        return ValidatedPhenotypeSource(
            layout="demo_artifact_store",
            data_version=data_version,
            config_sha256=config_sha256,
            artifact_sha256={name: item.sha256 for name, item in manifests.items()},
            tables=tables,
        )

    if all(
        (root / name / f"{name}.dataset.json").is_file()
        for name in PRIMARY_LABEL_ARTIFACTS
    ):
        optional_present = [
            (root / name / f"{name}.dataset.json").is_file()
            for name in COMPLETE_SOFA_ARTIFACTS
        ]
        if any(optional_present) and not all(optional_present):
            raise ArtifactValidationError(
                "Complete-SOFA sensitivity artifacts are incomplete"
            )
        shock_sensitivity_present = all(
            (root / name / f"{name}.dataset.json").is_file()
            for name in SHOCK_SENSITIVITY_ARTIFACTS
        )
        infection_optional_present = [
            (root / name / f"{name}.dataset.json").is_file()
            for name in INFECTION_SENSITIVITY_ARTIFACTS
        ]
        if any(infection_optional_present) and not all(infection_optional_present):
            raise ArtifactValidationError(
                "Infection sensitivity artifacts are incomplete"
            )
        names = PRIMARY_LABEL_ARTIFACTS + (
            COMPLETE_SOFA_ARTIFACTS if all(optional_present) else ()
        ) + (SHOCK_SENSITIVITY_ARTIFACTS if shock_sensitivity_present else ()) + (
            INFECTION_SENSITIVITY_ARTIFACTS
            if all(infection_optional_present)
            else ()
        )
        manifests = {
            name: validate_partitioned_dataset(root / name, name)
            for name in names
        }
        data_version = _same(
            [item.data_version for item in manifests.values()], "data_version"
        )
        config_sha256 = _same(
            [item.config_sha256 for item in manifests.values()], "config_sha256"
        )
        tables = {
            name: read_partitioned_dataset(
                root / name, name, validated_manifest=manifests[name]
            )
            for name in names
        }
        return ValidatedPhenotypeSource(
            layout="partitioned_label_run",
            data_version=data_version,
            config_sha256=config_sha256,
            artifact_sha256={
                name: partitioned_dataset_sha256(item)
                for name, item in manifests.items()
            },
            tables=tables,
        )

    raise ArtifactValidationError(
        "Path is neither a complete demo run nor a partitioned label run"
    )


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    forbidden = FORBIDDEN_REPORT_COLUMNS & set(frame.columns)
    if forbidden:
        raise ValueError(
            "Phenotype evidence contains row identifiers: "
            + ", ".join(sorted(forbidden))
        )
    clean = frame.astype(object).where(pd.notna(frame), None)
    return clean.to_dict(orient="records")


def _validate_stay_selection(
    episodes: pd.DataFrame, stays: pd.DataFrame, name: str
) -> None:
    """Verify that a stay artifact is the deterministic first positive episode."""
    expected = first_sepsis_episode_per_stay(episodes)
    keys = ["stay_id", "t0", "antibiotic_id", "culture_id"]
    if stays["stay_id"].duplicated().any() or len(stays) != len(expected):
        raise ArtifactValidationError(f"{name} is inconsistent with its episodes")
    left = stays[keys].sort_values(keys, kind="stable").reset_index(drop=True)
    right = expected[keys].sort_values(keys, kind="stable").reset_index(drop=True)
    try:
        pd.testing.assert_frame_equal(left, right, check_dtype=False)
    except AssertionError:
        raise ArtifactValidationError(f"{name} is inconsistent with its episodes")


def _validate_label_relationships(source: ValidatedPhenotypeSource) -> None:
    episodes = source.tables["sepsis_episodes"]
    stays = source.tables["sepsis_stays"]
    shock = source.tables["septic_shock_stays"]
    _validate_stay_selection(episodes, stays, "sepsis_stays")
    if shock["stay_id"].duplicated().any() or set(shock["stay_id"]) != set(
        stays["stay_id"]
    ):
        raise ArtifactValidationError(
            "septic_shock_stays is inconsistent with sepsis_stays"
        )
    complete_episodes = source.tables.get("sepsis_episodes_complete_sofa")
    complete_stays = source.tables.get("sepsis_stays_complete_sofa")
    if (complete_episodes is None) != (complete_stays is None):
        raise ArtifactValidationError(
            "Complete-SOFA sensitivity artifacts are incomplete"
        )
    if complete_episodes is not None and complete_stays is not None:
        _validate_stay_selection(
            complete_episodes, complete_stays, "sepsis_stays_complete_sofa"
        )
    shock_sensitivities = source.tables.get(
        "septic_shock_concurrency_sensitivities"
    )
    if shock_sensitivities is not None:
        try:
            shock_concurrency_sensitivity_summary(shock, shock_sensitivities)
        except ValueError as error:
            raise ArtifactValidationError(
                "Shock concurrency sensitivity artifact is inconsistent"
            ) from error
    infection_pairs = source.tables.get("infection_sensitivity_pairs")
    infection_episodes = source.tables.get("infection_sensitivity_episodes")
    infection_stays = source.tables.get("infection_sensitivity_stays")
    if any(item is not None for item in (
        infection_pairs, infection_episodes, infection_stays
    )) and not all(item is not None for item in (
        infection_pairs, infection_episodes, infection_stays
    )):
        raise ArtifactValidationError("Infection sensitivity artifacts are incomplete")
    if (
        infection_pairs is not None
        and infection_episodes is not None
        and infection_stays is not None
    ):
        pair_variants = set(infection_pairs["sensitivity"].dropna())
        episode_variants = set(infection_episodes["sensitivity"].dropna())
        stay_variants = set(infection_stays["sensitivity"].dropna())
        if not episode_variants.issubset(pair_variants) or not stay_variants.issubset(
            episode_variants
        ):
            raise ArtifactValidationError(
                "Infection sensitivity variants are inconsistent"
            )
        for name in episode_variants:
            variant_episodes = infection_episodes.loc[
                infection_episodes["sensitivity"].eq(name)
            ].drop(columns="sensitivity")
            variant_stays = infection_stays.loc[
                infection_stays["sensitivity"].eq(name)
            ].drop(columns="sensitivity")
            _validate_stay_selection(
                variant_episodes,
                variant_stays,
                f"infection_sensitivity_stays[{name}]",
            )


def build_phenotype_evidence(
    source: ValidatedPhenotypeSource,
    *,
    protocol_status: Mapping[str, str],
) -> dict[str, Any]:
    """Return the stable, timestamp-free content of a freeze-review report."""
    _validate_label_relationships(source)
    pairs = source.tables["suspected_infection_pairs"]
    episodes = source.tables["sepsis_episodes"]
    sepsis_stays = source.tables["sepsis_stays"]
    shock_stays = source.tables["septic_shock_stays"]
    complete_episodes = source.tables.get("sepsis_episodes_complete_sofa")
    complete_available = complete_episodes is not None
    shock_sensitivities = source.tables.get(
        "septic_shock_concurrency_sensitivities"
    )
    shock_sensitivity_available = shock_sensitivities is not None
    infection_sensitivity_pairs = source.tables.get(
        "infection_sensitivity_pairs"
    )
    infection_sensitivity_stays = source.tables.get(
        "infection_sensitivity_stays"
    )
    infection_sensitivity_available = (
        infection_sensitivity_pairs is not None
        and infection_sensitivity_stays is not None
    )
    decisions = decision_evidence_summary(
        complete_sofa_available=complete_available,
        shock_sensitivity_available=shock_sensitivity_available,
        infection_sensitivity_available=infection_sensitivity_available,
    ).copy()
    decisions["current_status"] = decisions["decision_id"].map(protocol_status)
    if decisions["current_status"].isna().any():
        missing = decisions.loc[
            decisions["current_status"].isna(), "decision_id"
        ].tolist()
        raise ValueError("Protocol status is missing decisions: " + ", ".join(missing))

    frames = {
        "phenotype_summary": phenotype_summary(
            pairs, episodes, sepsis_stays, shock_stays
        ),
        "infection_timing": infection_timing_summary(pairs),
        "infection_evidence_sensitivities": (
            infection_evidence_sensitivity_summary(
                pairs,
                sepsis_stays,
                infection_sensitivity_pairs,
                infection_sensitivity_stays,
            )
            if infection_sensitivity_available
            else unavailable_infection_evidence_sensitivities()
        ),
        "pair_multiplicity": pair_multiplicity(pairs),
        "coverage": coverage_summary(episodes),
        "coverage_sensitivities": coverage_sensitivity_summary(episodes),
        "complete_sofa_sensitivities": (
            complete_sofa_sensitivity_summary(complete_episodes)
            if complete_episodes is not None
            else unavailable_complete_sofa_sensitivity()
        ),
        "sofa_completeness_at_t0": sofa_completeness_summary(sepsis_stays),
        "shock_proxy": shock_proxy_summary(shock_stays),
        "shock_concurrency_sensitivities": (
            shock_concurrency_sensitivity_summary(
                shock_stays, shock_sensitivities
            )
            if shock_sensitivities is not None
            else unavailable_shock_concurrency_sensitivities()
        ),
        "decision_evidence": decisions,
    }
    if tuple(frames) != REPORT_TABLES:
        raise RuntimeError("Internal phenotype report table order changed")
    return {
        "schema_version": 4,
        "purpose": "protocol_freeze_review_only",
        "distribution_class": "protected_aggregate_unsuppressed_counts",
        "clinical_status_mutated": False,
        "source": {
            "layout": source.layout,
            "data_version": source.data_version,
            "config_sha256": source.config_sha256,
            "artifact_sha256": dict(source.artifact_sha256),
        },
        "definitions": {
            "D002": "not comparable within one cohort-policy run",
            "D004": (
                "first qualifying EMAR administration plus blood culture; "
                "prescription-start sensitivity is independently recomputed "
                "when available"
            ),
            "D010": (
                "EHR shock proxy; adequate fluids are not inferred; concurrency "
                "sensitivities are independently recomputed when available"
            ),
            "D011": (
                "coverage sensitivities, descriptive primary-t0 missingness and "
                "an independently recomputed sofa_complete sensitivity when its "
                "versioned artifacts are present"
            ),
        },
        "tables": {name: _records(frame) for name, frame in frames.items()},
    }


def evidence_sha256(content: Mapping[str, Any]) -> str:
    """Hash stable report content independently of generation time and path."""
    return protected_evidence_sha256(content)


def write_phenotype_evidence(
    path: str | Path, content: Mapping[str, Any]
) -> str:
    """Atomically persist protected aggregate evidence with restrictive mode."""
    return write_protected_evidence(path, content)


def read_phenotype_evidence(path: str | Path) -> dict[str, Any]:
    """Read a report and fail closed when its content digest does not match."""
    try:
        return read_protected_evidence(path)
    except ArtifactValidationError as error:
        raise ArtifactValidationError(
            str(error).replace("protected evidence", "phenotype evidence")
            .replace("Protected evidence", "Phenotype evidence")
        ) from error
