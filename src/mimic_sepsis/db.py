"""Safe connection and access checks for a local MIMIC-IV PostgreSQL database."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from sqlalchemy import Engine, create_engine, inspect, text

from .config import MIMICSettings


DEFAULT_REQUIRED_TABLES: Mapping[str, tuple[str, ...]] = {
    "mimiciv_hosp": ("admissions", "patients", "diagnoses_icd", "labevents"),
    "mimiciv_icu": ("icustays", "chartevents", "inputevents"),
}


@dataclass(frozen=True)
class AccessReport:
    """Result of a read-only connectivity and metadata check."""

    connected: bool
    available_schemas: tuple[str, ...]
    missing_schemas: tuple[str, ...]
    missing_tables: Mapping[str, tuple[str, ...]]

    @property
    def ready(self) -> bool:
        return self.connected and not self.missing_schemas and not any(self.missing_tables.values())


def create_mimic_engine(
    settings: MIMICSettings | None = None,
    *,
    pool_pre_ping: bool = True,
    echo: bool = False,
) -> Engine:
    """Create a lazy SQLAlchemy engine; no connection occurs until first use."""
    resolved = settings or MIMICSettings.from_env()
    return create_engine(
        resolved.sqlalchemy_url(),
        pool_pre_ping=pool_pre_ping,
        echo=echo,
    )


def get_table_names(engine: Engine, schema: str) -> tuple[str, ...]:
    """Return sorted table names visible to the current database user."""
    return tuple(sorted(inspect(engine).get_table_names(schema=schema)))


def check_mimic_access(
    engine: Engine,
    required_tables: Mapping[str, Iterable[str]] | None = None,
) -> AccessReport:
    """Check connectivity and required objects without reading patient rows."""
    requirements = DEFAULT_REQUIRED_TABLES if required_tables is None else required_tables
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))

    inspector = inspect(engine)
    available = tuple(sorted(inspector.get_schema_names()))
    available_set = set(available)
    missing_schemas = tuple(sorted(set(requirements) - available_set))
    missing_tables: dict[str, tuple[str, ...]] = {}
    for schema, required in requirements.items():
        if schema not in available_set:
            missing_tables[schema] = tuple(sorted(set(required)))
            continue
        existing = set(inspector.get_table_names(schema=schema))
        missing_tables[schema] = tuple(sorted(set(required) - existing))

    return AccessReport(
        connected=True,
        available_schemas=available,
        missing_schemas=missing_schemas,
        missing_tables=missing_tables,
    )
