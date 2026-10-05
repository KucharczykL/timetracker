"""PostgreSQL URL parsing and connection-contract startup wiring."""

import sys

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
        "postgresql://db",
        "postgresql:///tracker",
        "postgresql://db/tracker#fragment",
        "not a url",
    ],
)
def test_database_url_rejects_malformed_urls(url):
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


def _settings_with(
    monkeypatch,
    tmp_path,
    value: str | None,
    *,
    url: str = "postgresql://timetracker@127.0.0.1/tracker",
    check_interval: str | None = None,
):
    from timetracker import config as config_module
    from timetracker.database import required_database_settings

    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.delenv("DATABASE_CLIENT_CONNECTION_CHECK_INTERVAL", raising=False)
    if check_interval is not None:
        monkeypatch.setenv("DATABASE_CLIENT_CONNECTION_CHECK_INTERVAL", check_interval)
    monkeypatch.delenv("TIMETRACKER_MANAGED_DATABASE_URL", raising=False)
    monkeypatch.delenv("DISABLE_SERVER_SIDE_CURSORS", raising=False)
    if value is not None:
        monkeypatch.setenv("DISABLE_SERVER_SIDE_CURSORS", value)
    monkeypatch.setenv("ENV_FILE", str(tmp_path / "missing.env"))
    monkeypatch.setenv("INI_FILE", str(tmp_path / "missing.ini"))
    config_module.reset_caches()
    try:
        return required_database_settings()
    finally:
        config_module.reset_caches()


def test_server_side_cursors_stay_on_by_default(monkeypatch, tmp_path):
    settings = _settings_with(monkeypatch, tmp_path, None)
    assert settings["DISABLE_SERVER_SIDE_CURSORS"] is False


def test_server_side_cursors_can_be_turned_off(monkeypatch, tmp_path):
    settings = _settings_with(monkeypatch, tmp_path, "true")
    assert settings["DISABLE_SERVER_SIDE_CURSORS"] is True


def test_a_misspelled_value_reads_as_off(monkeypatch, tmp_path):
    """`cast=bool` raises on nothing: `ture` is off."""
    settings = _settings_with(monkeypatch, tmp_path, "ture")
    assert settings["DISABLE_SERVER_SIDE_CURSORS"] is False


def test_the_setting_sits_beside_engine_not_inside_options(monkeypatch, tmp_path):
    settings = _settings_with(monkeypatch, tmp_path, "true")
    assert "ENGINE" in settings
    assert "DISABLE_SERVER_SIDE_CURSORS" not in settings["OPTIONS"]


def test_connection_validation_rejects_a_contract_violation(monkeypatch):
    from timetracker.database import validate_default_connection
    from timetracker.postgres_contract import PostgresContractViolation

    class Connection:
        alias = "default"

    monkeypatch.setattr(
        "timetracker.database.observe_valid_postgres_connection",
        lambda connection: (_ for _ in ()).throw(PostgresContractViolation("wrong")),
    )

    with pytest.raises(ImproperlyConfigured, match="PostgreSQL database contract"):
        validate_default_connection(sender=None, connection=Connection())


def test_connection_validation_ignores_non_default_connections(monkeypatch):
    from timetracker.database import validate_default_connection

    class Connection:
        alias = "replica"

    monkeypatch.setattr(
        "timetracker.database.observe_valid_postgres_connection",
        lambda connection: pytest.fail("should not validate replica"),
    )

    validate_default_connection(sender=None, connection=Connection())


def test_a_backend_checks_for_its_client_every_10s(monkeypatch, tmp_path):
    """A dead client's query stops within the interval."""
    monkeypatch.setattr(sys, "platform", "linux")
    settings = _settings_with(monkeypatch, tmp_path, None)
    assert settings["OPTIONS"] == {"options": "-c client_connection_check_interval=10s"}


def test_django_on_windows_sends_no_check_by_default(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    settings = _settings_with(monkeypatch, tmp_path, None)
    assert settings["OPTIONS"] == {}


def test_the_check_interval_keeps_the_urls_options(monkeypatch, tmp_path):
    settings = _settings_with(
        monkeypatch,
        tmp_path,
        None,
        url="postgresql://db.example/tracker?options=-c%20search_path%3Dpublic",
        check_interval="3",
    )
    assert settings["OPTIONS"] == {
        "options": "-c search_path=public -c client_connection_check_interval=3s"
    }


def test_a_zero_check_interval_sends_no_option(monkeypatch, tmp_path):
    settings = _settings_with(monkeypatch, tmp_path, None, check_interval="0")
    assert settings["OPTIONS"] == {}


@pytest.mark.parametrize("value", ["10s", "-5", ""])
def test_a_check_interval_that_is_no_count_of_seconds_names_itself(
    monkeypatch, tmp_path, value
):
    with pytest.raises(
        ImproperlyConfigured, match="DATABASE_CLIENT_CONNECTION_CHECK_INTERVAL"
    ):
        _settings_with(monkeypatch, tmp_path, None, check_interval=value)


@pytest.mark.django_db
def test_the_server_accepts_the_check_interval():
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("SHOW client_connection_check_interval")
        assert cursor.fetchone()[0] != "0"


def _fresh_statement_timeout() -> str:
    from django.db import connections

    fresh = connections.create_connection("default")
    try:
        with fresh.cursor() as cursor:
            cursor.execute("SHOW statement_timeout")
            return cursor.fetchone()[0]
    finally:
        fresh.close()


@pytest.mark.django_db
def test_a_command_keeps_no_statement_limit():
    assert _fresh_statement_timeout() == "0"


@pytest.mark.django_db
def test_a_process_serving_requests_stops_a_statement_at_30s(monkeypatch):
    from timetracker.database import limit_request_statements

    monkeypatch.delenv("REQUEST_STATEMENT_TIMEOUT", raising=False)
    limit_request_statements()

    assert _fresh_statement_timeout() == "30s"


@pytest.mark.django_db
def test_a_request_limit_of_0_lifts_it(monkeypatch):
    from timetracker.database import limit_request_statements

    monkeypatch.setenv("REQUEST_STATEMENT_TIMEOUT", "0")
    limit_request_statements()

    assert _fresh_statement_timeout() == "0"


@pytest.mark.django_db
@pytest.mark.parametrize("entry_point", ["timetracker.asgi", "timetracker.wsgi"])
def test_each_entry_point_marks_its_process(monkeypatch, entry_point):
    import importlib

    from timetracker import database

    monkeypatch.delenv("REQUEST_STATEMENT_TIMEOUT", raising=False)
    sys.modules.pop(entry_point, None)
    importlib.import_module(entry_point)

    assert database._ProcessStatements.timeout_seconds == 30
