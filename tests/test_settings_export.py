from configparser import ConfigParser

import pytest

from games.models import SiteSetting
from timetracker import config as config_module
from timetracker.config import INI_SECTION, resolve_raw_with_source
from timetracker.settings_export import export_site_settings_ini


@pytest.fixture
def clean_ini_env(monkeypatch, tmp_path):
    """Point the real reader at a scratch file so round-trip tests exercise the
    production read path without touching the repo's settings.ini."""
    monkeypatch.delenv("DEFAULT_CURRENCY", raising=False)
    monkeypatch.setenv("ENV_FILE", str(tmp_path / "missing.env"))
    ini_path = tmp_path / "settings.ini"
    monkeypatch.setenv("INI_FILE", str(ini_path))
    config_module.reset_caches()
    return ini_path


def test_no_site_settings_produces_bare_section(db):
    text = export_site_settings_ini()
    parser = ConfigParser()
    parser.read_string(text)
    assert parser.has_section(INI_SECTION)
    assert dict(parser[INI_SECTION]) == {}


def test_exports_one_row_per_stored_key(db):
    SiteSetting.objects.create(key="DEFAULT_CURRENCY", value="EUR")
    SiteSetting.objects.create(key="DEFAULT_PAGE_SIZE", value=50)

    text = export_site_settings_ini()

    parser = ConfigParser()
    parser.optionxform = str  # type: ignore[assignment, method-assign]
    parser.read_string(text)
    assert dict(parser[INI_SECTION]) == {
        "DEFAULT_CURRENCY": "EUR",
        "DEFAULT_PAGE_SIZE": "50",
    }


def test_stale_unregistered_key_is_exported_anyway(db):
    """A row for a since-removed/renamed registry key is still a real DB value —
    drop it silently and a backup snapshot loses data the operator expected. An
    unknown key in the ini is harmless on re-import (nothing looks it up), so
    export everything the DB actually holds rather than filtering by the
    current registry."""
    SiteSetting.objects.create(key="DEFAULT_CURRENCY", value="EUR")
    SiteSetting.objects.create(key="SOME_REMOVED_SETTING", value="stale")

    text = export_site_settings_ini()

    parser = ConfigParser()
    parser.optionxform = str  # type: ignore[assignment, method-assign]
    parser.read_string(text)
    assert dict(parser[INI_SECTION]) == {
        "DEFAULT_CURRENCY": "EUR",
        "SOME_REMOVED_SETTING": "stale",
    }


def test_page_size_round_trips_through_cast_and_validator(db, clean_ini_env):
    """Acceptance criterion, checked past the raw string layer: the exported
    value must resolve back to the identical typed value through the full
    resolver (cast + validator), not just match byte-for-byte as a string."""
    SiteSetting.objects.create(key="DEFAULT_PAGE_SIZE", value=50)

    text = export_site_settings_ini()
    clean_ini_env.write_text(text)
    config_module.reset_caches()

    from timetracker.settings_resolver import resolve_with_origin

    resolved = resolve_with_origin("DEFAULT_PAGE_SIZE")
    assert resolved.value == 50


def test_percent_bearing_value_round_trips_through_the_real_reader(db, clean_ini_env):
    """Acceptance criterion from #392: a value containing `%` must re-import
    to the identical value through the actual production reader, not a
    reimplementation of it."""
    SiteSetting.objects.create(key="DEFAULT_CURRENCY", value="EU%R")

    text = export_site_settings_ini()
    clean_ini_env.write_text(text)
    config_module.reset_caches()

    result = resolve_raw_with_source("DEFAULT_CURRENCY")
    assert result is not None
    assert result.raw == "EU%R"


def test_exported_values_are_never_quoted(db):
    SiteSetting.objects.create(key="DEFAULT_CURRENCY", value="EUR")

    text = export_site_settings_ini()

    line = next(
        line for line in text.splitlines() if line.startswith("DEFAULT_CURRENCY")
    )
    assert '"' not in line
    assert "'" not in line
