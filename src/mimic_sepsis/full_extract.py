"""Out-of-core extraction of cohort-scoped MIMIC-IV CSV sources."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
from typing import Iterable

import duckdb

from .feature_sources import LAB_ITEMS, VITAL_ITEMS
from .sofa_hourly import HEART_RATE_ITEMID
from .sofa_labs import LAB_COMPONENTS
from .sofa_neuro_cardio import GCS_ITEMS, MAP_ITEMID, VASOACTIVE_ITEMS
from .sofa_resp_renal import (
    FIO2_ITEMID, INVASIVE_VENTILATION_ITEMID, PAO2_ITEMID, URINE_OUTPUT_ITEMIDS,
)
from .septic_shock import LACTATE_ITEMIDS, VASOPRESSOR_ITEMS


CHARTEVENT_ITEMIDS = frozenset(VITAL_ITEMS) | frozenset(GCS_ITEMS) | {
    HEART_RATE_ITEMID, MAP_ITEMID, FIO2_ITEMID,
}
LABEVENT_ITEMIDS = frozenset(LAB_ITEMS) | frozenset(LAB_COMPONENTS) | {
    PAO2_ITEMID,
} | frozenset(LACTATE_ITEMIDS)
INPUTEVENT_ITEMIDS = frozenset(VASOACTIVE_ITEMS) | frozenset(VASOPRESSOR_ITEMS)


@dataclass(frozen=True)
class ExtractManifest:
    artifact: str
    rows: int
    columns: tuple[str, ...]
    sha256: str
    data_version: str
    config_sha256: str


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sql_path(path: Path) -> str:
    return str(path.resolve()).replace("'", "''")


def _ids(values: Iterable[int]) -> str:
    return ",".join(str(int(value)) for value in sorted(set(values)))


class FullCSVExtractor:
    """Stream cohort-scoped tables from compressed CSV to Parquet via DuckDB."""

    def __init__(
        self,
        data_dir: Path,
        output_dir: Path,
        *,
        data_version: str,
        memory_limit: str = "4GB",
        temp_dir: Path | None = None,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.output_dir = Path(output_dir)
        self.data_version = str(data_version)
        self.memory_limit = memory_limit
        self.temp_dir = Path(temp_dir or output_dir / "tmp")
        self.config = {
            "backend": "duckdb-out-of-core-csv",
            "cohort_policy": "first_per_admission",
            "data_version": self.data_version,
            "extractor_schema_version": 3,
            "itemids": {
                "chartevents": sorted(CHARTEVENT_ITEMIDS),
                "labevents": sorted(LABEVENT_ITEMIDS),
                "inputevents": sorted(INPUTEVENT_ITEMIDS),
                "outputevents": sorted(URINE_OUTPUT_ITEMIDS),
                "procedureevents": [INVASIVE_VENTILATION_ITEMID],
            },
        }
        self.config_hash = hashlib.sha256(
            json.dumps(self.config, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def _view(self, connection, name: str, relative: str) -> None:
        path = _sql_path(self.data_dir / relative)
        connection.execute(
            f"CREATE OR REPLACE VIEW {name} AS SELECT * FROM read_csv_auto('{path}', header=true)"
        )

    def _write(self, connection, name: str, query: str, *, resume: bool) -> ExtractManifest:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        target = self.output_dir / f"{name}.parquet"
        manifest_path = self.output_dir / f"{name}.manifest.json"
        if resume and target.is_file() and manifest_path.is_file():
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest = ExtractManifest(**{**raw, "columns": tuple(raw["columns"])})
            if manifest.config_sha256 == self.config_hash and _hash_file(target) == manifest.sha256:
                return manifest
        temporary = self.output_dir / f".{name}.partial.parquet"
        temporary.unlink(missing_ok=True)
        escaped = _sql_path(temporary)
        try:
            connection.execute(
                f"COPY ({query}) TO '{escaped}' (FORMAT PARQUET, COMPRESSION ZSTD)"
            )
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        temporary.replace(target)
        description = connection.execute(
            f"DESCRIBE SELECT * FROM read_parquet('{_sql_path(target)}')"
        ).fetchdf()
        rows = connection.execute(
            f"SELECT count(*) FROM read_parquet('{_sql_path(target)}')"
        ).fetchone()[0]
        manifest = ExtractManifest(
            artifact=name,
            rows=int(rows),
            columns=tuple(description["column_name"].astype(str)),
            sha256=_hash_file(target),
            data_version=self.data_version,
            config_sha256=self.config_hash,
        )
        manifest_path.write_text(
            json.dumps(asdict(manifest), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return manifest

    def run(self, *, resume: bool = False) -> list[ExtractManifest]:
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        connection = duckdb.connect()
        try:
            connection.execute(f"SET memory_limit='{self.memory_limit}'")
            connection.execute(f"SET temp_directory='{_sql_path(self.temp_dir)}'")
            for name, relative in {
                "patients": "hosp/patients.csv.gz",
                "admissions": "hosp/admissions.csv.gz",
                "icustays": "icu/icustays.csv.gz",
                "chartevents": "icu/chartevents.csv.gz",
                "labevents": "hosp/labevents.csv.gz",
                "inputevents": "icu/inputevents.csv.gz",
                "outputevents": "icu/outputevents.csv.gz",
                "procedureevents": "icu/procedureevents.csv.gz",
                "prescriptions": "hosp/prescriptions.csv.gz",
                "emar": "hosp/emar.csv.gz",
                "microbiology": "hosp/microbiologyevents.csv.gz",
            }.items():
                self._view(connection, name, relative)
            connection.execute("""
                CREATE TEMP TABLE cohort_evaluated AS
                SELECT i.subject_id, i.hadm_id, i.stay_id, i.intime, i.outtime,
                       p.anchor_age + year(i.intime) - p.anchor_year AS age_at_icu,
                       CASE
                         WHEN p.subject_id IS NULL THEN 'missing_patient_link'
                         WHEN a.hadm_id IS NULL THEN 'missing_admission_link'
                         WHEN i.intime IS NULL OR i.outtime IS NULL THEN 'missing_timestamp'
                         WHEN i.outtime <= i.intime THEN 'non_positive_duration'
                         WHEN p.anchor_age IS NULL OR p.anchor_year IS NULL THEN 'missing_age'
                         WHEN p.anchor_age + year(i.intime) - p.anchor_year < 18 THEN 'younger_than_minimum_age'
                         ELSE NULL
                       END AS initial_exclusion_reason
                FROM icustays i
                LEFT JOIN patients p USING (subject_id)
                LEFT JOIN admissions a USING (subject_id, hadm_id)
            """)
            connection.execute("""
                CREATE TEMP TABLE cohort_ranked AS
                SELECT *, row_number() OVER (
                    PARTITION BY subject_id, hadm_id ORDER BY intime, stay_id
                ) AS stay_rank
                FROM cohort_evaluated
                WHERE initial_exclusion_reason IS NULL
            """)
            connection.execute("""
                CREATE TEMP VIEW cohort AS
                SELECT subject_id, hadm_id, stay_id, intime, outtime, age_at_icu
                FROM cohort_ranked WHERE stay_rank=1
            """)
            manifests = [self._write(
                connection, "cohort_stays",
                "SELECT * FROM cohort ORDER BY subject_id, intime, stay_id",
                resume=resume,
            )]
            manifests.append(self._write(
                connection, "cohort_audit",
                """SELECT e.subject_id, e.hadm_id, e.stay_id, e.intime, e.outtime,
                          e.age_at_icu, r.stay_rank, coalesce(
                            e.initial_exclusion_reason,
                            CASE WHEN r.stay_rank>1 THEN 'not_selected:first_per_admission' END
                          ) AS exclusion_reason,
                          coalesce(r.stay_rank=1, false) AS selected
                   FROM cohort_evaluated e LEFT JOIN cohort_ranked r USING(stay_id)
                   ORDER BY e.subject_id, e.intime, e.stay_id""",
                resume=resume,
            ))
            queries = {
                "chartevents_reduced": f"""
                    SELECT e.stay_id, e.itemid, e.charttime, e.value, e.valuenum
                    FROM chartevents e JOIN cohort c USING (stay_id)
                    WHERE e.itemid IN ({_ids(CHARTEVENT_ITEMIDS)})
                      AND e.charttime >= c.intime AND e.charttime < c.outtime
                """,
                "labevents_reduced": f"""
                    SELECT e.subject_id, e.hadm_id, e.itemid, e.charttime,
                           e.storetime, e.valuenum, e.valueuom
                    FROM labevents e JOIN cohort c USING (subject_id, hadm_id)
                    WHERE e.itemid IN ({_ids(LABEVENT_ITEMIDS)})
                      AND e.charttime >= c.intime AND e.charttime < c.outtime
                """,
                "inputevents_reduced": f"""
                    SELECT e.stay_id, e.itemid, e.starttime, e.endtime,
                           e.rate, e.rateuom
                    FROM inputevents e JOIN cohort c USING (stay_id)
                    WHERE e.itemid IN ({_ids(INPUTEVENT_ITEMIDS)})
                """,
                "outputevents_reduced": f"""
                    SELECT e.stay_id, e.itemid, e.charttime, e.value
                    FROM outputevents e JOIN cohort c USING (stay_id)
                    WHERE e.itemid IN ({_ids(URINE_OUTPUT_ITEMIDS)})
                """,
                "procedureevents_reduced": f"""
                    SELECT e.stay_id, e.itemid, e.starttime, e.endtime
                    FROM procedureevents e JOIN cohort c USING (stay_id)
                    WHERE e.itemid={INVASIVE_VENTILATION_ITEMID}
                """,
                "prescriptions_cohort": """SELECT e.subject_id, e.hadm_id, e.pharmacy_id,
                                                   e.starttime, e.drug_type, e.drug, e.route
                                            FROM prescriptions e JOIN
                                              (SELECT DISTINCT subject_id,hadm_id FROM cohort) c
                                            USING(subject_id,hadm_id)""",
                "emar_cohort": """SELECT e.subject_id, e.hadm_id, e.pharmacy_id,
                                           e.charttime, e.event_txt
                                    FROM emar e JOIN
                                      (SELECT DISTINCT subject_id,hadm_id FROM cohort) c
                                    USING(subject_id,hadm_id)""",
                "microbiology_cohort": """SELECT e.subject_id, e.hadm_id,
                                                   e.micro_specimen_id, e.charttime,
                                                   e.chartdate, e.spec_type_desc
                                            FROM microbiology e JOIN
                                              (SELECT DISTINCT subject_id,hadm_id FROM cohort) c
                                            USING(subject_id,hadm_id)""",
            }
            for name, query in queries.items():
                manifests.append(self._write(connection, name, query, resume=resume))
            return manifests
        finally:
            connection.close()
