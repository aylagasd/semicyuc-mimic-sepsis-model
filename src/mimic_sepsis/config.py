"""Environment-based database configuration with no embedded credentials."""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Mapping

from sqlalchemy.engine import URL, make_url


DEFAULT_SCHEMAS = ("mimiciv_hosp", "mimiciv_icu", "mimiciv_derived")


@dataclass(frozen=True)
class MIMICSettings:
    """Connection settings for a PostgreSQL installation of MIMIC-IV.

    Prefer ``MIMIC_DATABASE_URL`` when a complete SQLAlchemy URL is already
    available. Otherwise the individual ``MIMIC_DB_*`` variables are used.
    """

    database_url: str | None = None
    host: str = "localhost"
    port: int = 5432
    database: str = "mimiciv"
    user: str = "postgres"
    password: str | None = None
    sslmode: str | None = None
    schemas: tuple[str, ...] = DEFAULT_SCHEMAS

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "MIMICSettings":
        env = os.environ if environ is None else environ
        schemas = tuple(
            item.strip()
            for item in env.get("MIMIC_DB_SCHEMAS", ",".join(DEFAULT_SCHEMAS)).split(",")
            if item.strip()
        )
        try:
            port = int(env.get("MIMIC_DB_PORT", "5432"))
        except ValueError as exc:
            raise ValueError("MIMIC_DB_PORT must be an integer") from exc
        return cls(
            database_url=env.get("MIMIC_DATABASE_URL") or None,
            host=env.get("MIMIC_DB_HOST", "localhost"),
            port=port,
            database=env.get("MIMIC_DB_NAME", "mimiciv"),
            user=env.get("MIMIC_DB_USER", "postgres"),
            password=env.get("MIMIC_DB_PASSWORD") or None,
            sslmode=env.get("MIMIC_DB_SSLMODE") or None,
            schemas=schemas,
        )

    def sqlalchemy_url(self) -> URL:
        """Build a PostgreSQL URL while keeping the password as structured data."""
        if self.database_url:
            url = make_url(self.database_url)
            if not url.drivername.startswith("postgresql"):
                raise ValueError("MIMIC_DATABASE_URL must use a PostgreSQL driver")
            return url
        query = {"sslmode": self.sslmode} if self.sslmode else {}
        return URL.create(
            "postgresql+psycopg",
            username=self.user,
            password=self.password,
            host=self.host,
            port=self.port,
            database=self.database,
            query=query,
        )
