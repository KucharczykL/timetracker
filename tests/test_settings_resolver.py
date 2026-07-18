"""Tests for the layered, origin-aware settings resolver."""

import subprocess
import sys
from pathlib import Path

import pytest
from django.conf import settings as django_settings
from django.db.utils import OperationalError

from timetracker import config as config_module
from timetracker import settings_resolver
from timetracker.config import SettingSource
from timetracker.settings_resolver import (
    resolve,
    resolve_with_origin,
    set_site_setting,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def no_currency_env(monkeypatch):
    """Ensure no boot-frozen source supplies DEFAULT_CURRENCY, so the DB/default
    layers are what the test actually exercises."""
    monkeypatch.delenv("DEFAULT_CURRENCY", raising=False)
    monkeypatch.delenv("DEFAULT_CURRENCY__FILE", raising=False)
    config_module.reset_caches()
    settings_resolver.clear_cache()
    yield


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    def _write(contents: str):
        path = tmp_path / ".env"
        path.write_text(contents)
        monkeypatch.setenv("ENV_FILE", str(path))
        config_module.reset_caches()
        return path

    return _write


@pytest.fixture
def ini_file(tmp_path, monkeypatch):
    def _write(contents: str):
        path = tmp_path / "settings.ini"
        path.write_text(contents)
        monkeypatch.setenv("INI_FILE", str(path))
        config_module.reset_caches()
        return path

    return _write


def _write_currency_row(django_capture_on_commit_callbacks, value):
    with django_capture_on_commit_callbacks(execute=True):
        set_site_setting("DEFAULT_CURRENCY", value)


# --- precedence -----------------------------------------------------------


def test_env_beats_db(
    db, no_currency_env, monkeypatch, django_capture_on_commit_callbacks
):
    _write_currency_row(django_capture_on_commit_callbacks, "EUR")
    monkeypatch.setenv("DEFAULT_CURRENCY", "USD")
    config_module.reset_caches()
    result = resolve_with_origin("DEFAULT_CURRENCY")
    assert result.value == "USD"
    assert result.source is SettingSource.ENV
    assert result.locked is True


def test_dotenv_beats_db(
    db, no_currency_env, env_file, django_capture_on_commit_callbacks
):
    _write_currency_row(django_capture_on_commit_callbacks, "EUR")
    env_file("DEFAULT_CURRENCY=GBP\n")
    result = resolve_with_origin("DEFAULT_CURRENCY")
    assert result.value == "GBP"
    assert result.source is SettingSource.DOTENV
    assert result.locked is True


def test_ini_beats_db(
    db, no_currency_env, ini_file, django_capture_on_commit_callbacks
):
    _write_currency_row(django_capture_on_commit_callbacks, "EUR")
    ini_file("[timetracker]\nDEFAULT_CURRENCY = JPY\n")
    result = resolve_with_origin("DEFAULT_CURRENCY")
    assert result.value == "JPY"
    assert result.source is SettingSource.INI


def test_db_beats_default(db, no_currency_env, django_capture_on_commit_callbacks):
    _write_currency_row(django_capture_on_commit_callbacks, "EUR")
    result = resolve_with_origin("DEFAULT_CURRENCY")
    assert result.value == "EUR"
    assert result.source is SettingSource.DATABASE
    assert result.locked is False


def test_default_when_all_silent(db, no_currency_env):
    result = resolve_with_origin("DEFAULT_CURRENCY")
    assert result.value == django_settings.DEFAULT_CURRENCY
    assert result.source is SettingSource.DEFAULT
    assert result.locked is False


# --- origin / locking -----------------------------------------------------


def test_secret_key_file_origin(monkeypatch, tmp_path):
    secret_path = tmp_path / "secret"
    secret_path.write_text("s3cr3t\n")
    monkeypatch.setenv("SECRET_KEY__FILE", str(secret_path))
    config_module.reset_caches()
    result = resolve_with_origin("SECRET_KEY")
    assert result.value == "s3cr3t"
    assert result.source is SettingSource.ENV_FILE
    assert result.locked is True


# --- casting / normalization ----------------------------------------------


def test_db_value_is_cast_and_validated_like_env(db, no_currency_env):
    from games.models import SiteSetting

    # Raw lowercase row inserted directly (bypassing set_site_setting's normalize)
    # must still resolve normalized on read — proving the DB layer runs the cast.
    SiteSetting.objects.create(key="DEFAULT_CURRENCY", value="eur")
    settings_resolver.clear_cache()
    assert resolve("DEFAULT_CURRENCY") == "EUR"


def test_infra_scope_ignores_stray_db_row(db, monkeypatch):
    from games.models import SiteSetting

    monkeypatch.delenv("TZ", raising=False)
    config_module.reset_caches()
    SiteSetting.objects.create(key="TZ", value="Mars/Olympus")
    settings_resolver.clear_cache()
    result = resolve_with_origin("TZ")
    assert result.value == django_settings.TIME_ZONE
    assert result.source is SettingSource.DEFAULT


# --- cache invalidation ---------------------------------------------------


def test_cache_invalidation_on_write(
    db, no_currency_env, django_capture_on_commit_callbacks
):
    # Warm the cache with the empty-table (default) state.
    assert resolve_with_origin("DEFAULT_CURRENCY").source is SettingSource.DEFAULT
    _write_currency_row(django_capture_on_commit_callbacks, "eur")
    # on_commit invalidation ran → immediate, no TTL wait.
    result = resolve_with_origin("DEFAULT_CURRENCY")
    assert result.value == "EUR"
    assert result.source is SettingSource.DATABASE
    with django_capture_on_commit_callbacks(execute=True):
        settings_resolver.clear_site_setting("DEFAULT_CURRENCY")
    assert resolve_with_origin("DEFAULT_CURRENCY").source is SettingSource.DEFAULT


def test_queryset_update_is_invisible_until_ttl(db, no_currency_env, monkeypatch):
    from games.models import SiteSetting

    clock = {"now": 1000.0}
    monkeypatch.setattr(settings_resolver.time, "monotonic", lambda: clock["now"])
    SiteSetting.objects.create(key="DEFAULT_CURRENCY", value="EUR")
    settings_resolver.clear_cache()
    assert resolve("DEFAULT_CURRENCY") == "EUR"  # warms snapshot at t=1000
    # Raw update bypasses signals; stale until the TTL lapses.
    SiteSetting.objects.filter(key="DEFAULT_CURRENCY").update(value="GBP")
    assert resolve("DEFAULT_CURRENCY") == "EUR"
    clock["now"] += settings_resolver.SITE_SETTINGS_TTL_SECONDS + 1
    assert resolve("DEFAULT_CURRENCY") == "GBP"


def test_resolve_pair_hits_db_at_most_once(
    db, no_currency_env, django_assert_num_queries
):
    settings_resolver.clear_cache()
    with django_assert_num_queries(1):
        resolve("DEFAULT_CURRENCY")
        resolve("DEFAULT_CURRENCY")


# --- write guards ---------------------------------------------------------


def test_set_site_setting_rejects_unknown_key(db):
    with pytest.raises(KeyError):
        set_site_setting("NOPE", "x")


def test_set_site_setting_rejects_infra_key(db):
    with pytest.raises(ValueError):
        set_site_setting("TZ", "Europe/Prague")


def test_set_site_setting_rejects_invalid_and_writes_nothing(db):
    from django.core.exceptions import ValidationError
    from games.models import SiteSetting

    with pytest.raises(ValidationError):
        set_site_setting("DEFAULT_CURRENCY", "EURO")
    assert not SiteSetting.objects.filter(key="DEFAULT_CURRENCY").exists()


# --- DB-error guard -------------------------------------------------------


def test_missing_table_falls_back_without_caching(
    db, no_currency_env, monkeypatch, capture_games_logger
):
    def boom():
        raise OperationalError("no such table: games_sitesetting")

    monkeypatch.setattr(settings_resolver, "_load_snapshot", boom)
    with capture_games_logger():
        assert resolve("DEFAULT_CURRENCY") == django_settings.DEFAULT_CURRENCY
    # The failure was not cached — a later working read must retry.
    assert settings_resolver._snapshot is None


# --- no DB access at settings import --------------------------------------


def test_no_db_module_loaded_during_settings_import(monkeypatch):
    """Importing timetracker.settings must not pull the resolver or the ORM
    models (the only modules that could issue a query at settings-eval time).

    Run in a clean subprocess with a sanitized env so a developer's exported
    DEFAULT_CURRENCY/ENV_FILE can't change what loads.
    """
    script = (
        "import sys\n"
        "import timetracker.settings\n"
        "assert 'timetracker.settings_resolver' not in sys.modules, 'resolver imported'\n"
        "assert 'games.models' not in sys.modules, 'models imported'\n"
        "print('ok')\n"
    )
    env = {
        "PATH": __import__("os").environ.get("PATH", ""),
        "DJANGO_SETTINGS_MODULE": "timetracker.settings",
    }
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout
