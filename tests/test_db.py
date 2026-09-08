from unittest.mock import MagicMock, patch

from mimic_sepsis.config import MIMICSettings
from mimic_sepsis.db import check_mimic_access, create_mimic_engine, get_table_names


def test_create_engine_is_lazy_and_uses_structured_url():
    settings = MIMICSettings(host="db", user="analyst", password="secret")
    with patch("mimic_sepsis.db.create_engine") as factory:
        create_mimic_engine(settings)
    url = factory.call_args.args[0]
    assert url.host == "db"
    assert url.password == "secret"
    factory.assert_called_once_with(url, pool_pre_ping=True, echo=False)


@patch("mimic_sepsis.db.inspect")
def test_access_report_identifies_missing_objects(inspect_mock):
    engine = MagicMock()
    connection = engine.connect.return_value.__enter__.return_value
    inspector = inspect_mock.return_value
    inspector.get_schema_names.return_value = ["public", "mimiciv_hosp"]
    inspector.get_table_names.return_value = ["admissions"]

    report = check_mimic_access(
        engine,
        {"mimiciv_hosp": ["admissions", "patients"], "mimiciv_icu": ["icustays"]},
    )

    connection.execute.assert_called_once()
    assert report.connected
    assert not report.ready
    assert report.missing_schemas == ("mimiciv_icu",)
    assert report.missing_tables == {
        "mimiciv_hosp": ("patients",),
        "mimiciv_icu": ("icustays",),
    }


@patch("mimic_sepsis.db.inspect")
def test_get_table_names_is_sorted(inspect_mock):
    inspect_mock.return_value.get_table_names.return_value = ["patients", "admissions"]
    assert get_table_names(MagicMock(), "mimiciv_hosp") == ("admissions", "patients")
