"""PostgreSQL URL parsing and connection-contract startup wiring."""

import pytest
from django.core.exceptions import ImproperlyConfigured


def test_postgresql_url_maps_to_django_database_settings():
    from timetracker.database import database_settings_from_url

    assert database_settings_from_url(
        "postgresql://app%20user:secret%2Fvalue@db.example:5544/tracker?sslmode=require"
    ) == {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "tracker",
        "USER": "app user",
        "PASSWORD": "secret/value",
        "HOST": "db.example",
        "PORT": 5544,
        "OPTIONS": {"sslmode": "require"},
    }


@pytest.mark.parametrize(
    "url",
    [
        "mysql://db/tracker",
        "postgresql://db",
        "postgresql:///tracker",
        "postgresql://db/tracker#fragment",
        "not a url",
    ],
)
def test_database_url_rejects_non_postgresql_or_malformed_urls(url):
    from timetracker.database import database_settings_from_url

    with pytest.raises(ImproperlyConfigured, match="DATABASE_URL"):
        database_settings_from_url(url)


def test_missing_database_url_has_an_actionable_error(monkeypatch, tmp_path):
    from timetracker import config as config_module
    from timetracker.database import required_database_settings

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("ENV_FILE", str(tmp_path / "missing.env"))
    monkeypatch.setenv("INI_FILE", str(tmp_path / "missing.ini"))
    config_module.reset_caches()

    with pytest.raises(ImproperlyConfigured, match="DATABASE_URL is required"):
        required_database_settings()


def test_dotenv_database_url_overrides_a_managed_cached_url(monkeypatch, tmp_path):
    from timetracker import config as config_module
    from timetracker.database import required_database_settings

    dotenv = tmp_path / ".env"
    dotenv.write_text("DATABASE_URL=postgresql://configured.example/tracker\n")
    monkeypatch.setenv("DATABASE_URL", "postgresql://timetracker@127.0.0.1/cache")
    monkeypatch.setenv("TIMETRACKER_MANAGED_DATABASE_URL", "1")
    monkeypatch.setenv("ENV_FILE", str(dotenv))
    monkeypatch.setenv("INI_FILE", str(tmp_path / "missing.ini"))
    config_module.reset_caches()

    try:
        assert required_database_settings()["HOST"] == "configured.example"
    finally:
        config_module.reset_caches()


def test_file_database_url_wins_over_plain_environment(monkeypatch, tmp_path):
    from timetracker import config as config_module
    from timetracker.database import required_database_settings

    secret = tmp_path / "database_url"
    secret.write_text("postgresql://file.example/tracker\n")
    monkeypatch.setenv("DATABASE_URL__FILE", str(secret))
    monkeypatch.setenv("DATABASE_URL", "postgresql://plain.example/tracker")
    monkeypatch.delenv("TIMETRACKER_MANAGED_DATABASE_URL", raising=False)
    monkeypatch.setenv("ENV_FILE", str(tmp_path / "missing.env"))
    monkeypatch.setenv("INI_FILE", str(tmp_path / "missing.ini"))
    config_module.reset_caches()

    try:
        assert required_database_settings()["HOST"] == "file.example"
    finally:
        config_module.reset_caches()


def test_project_settings_use_required_postgresql_database_configuration():
    from timetracker import settings as project_settings

    assert (
        project_settings.DATABASES["default"]["ENGINE"]
        == "django.db.backends.postgresql"
    )


def test_connection_validation_rejects_a_contract_violation(monkeypatch):
    from timetracker.database import validate_default_connection
    from timetracker.postgres_contract import PostgresContractViolation

    class Connection:
        alias = "default"

    monkeypatch.setattr(
        "timetracker.database.validate_postgres_collation_contract",
        lambda connection: (_ for _ in ()).throw(PostgresContractViolation("wrong")),
    )

    with pytest.raises(ImproperlyConfigured, match="PostgreSQL database contract"):
        validate_default_connection(sender=None, connection=Connection())


def test_connection_validation_ignores_non_default_connections(monkeypatch):
    from timetracker.database import validate_default_connection

    class Connection:
        alias = "replica"

    monkeypatch.setattr(
        "timetracker.database.validate_postgres_collation_contract",
        lambda connection: pytest.fail("should not validate replica"),
    )

    validate_default_connection(sender=None, connection=Connection())
