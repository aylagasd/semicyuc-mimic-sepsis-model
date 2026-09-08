from sqlalchemy.engine import URL
import pytest

from mimic_sepsis.config import MIMICSettings


def test_settings_from_individual_environment_variables():
    settings = MIMICSettings.from_env(
        {
            "MIMIC_DB_HOST": "db.internal",
            "MIMIC_DB_PORT": "6543",
            "MIMIC_DB_NAME": "mimic",
            "MIMIC_DB_USER": "researcher",
            "MIMIC_DB_PASSWORD": "secret",
            "MIMIC_DB_SCHEMAS": "mimiciv_hosp, mimiciv_icu",
        }
    )
    url = settings.sqlalchemy_url()
    assert isinstance(url, URL)
    assert url.host == "db.internal"
    assert url.password == "secret"
    assert settings.schemas == ("mimiciv_hosp", "mimiciv_icu")
    assert "secret" not in url.render_as_string(hide_password=True)


def test_database_url_takes_precedence():
    settings = MIMICSettings.from_env(
        {"MIMIC_DATABASE_URL": "postgresql+psycopg://alice:p%40ss@db/mimic"}
    )
    assert settings.sqlalchemy_url().username == "alice"
    assert settings.sqlalchemy_url().password == "p@ss"


def test_rejects_non_postgresql_database_url():
    with pytest.raises(ValueError, match="PostgreSQL"):
        MIMICSettings(database_url="sqlite:///mimic.db").sqlalchemy_url()


def test_rejects_invalid_port():
    with pytest.raises(ValueError, match="integer"):
        MIMICSettings.from_env({"MIMIC_DB_PORT": "not-a-port"})
