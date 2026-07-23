"""Tests for the declarative settings registry (no DB access)."""

from dataclasses import FrozenInstanceError

import pytest
from django.core.exceptions import ValidationError

from games.models import UserPreferences
from timetracker import settings_registry
from timetracker.settings_registry import (
    SETTINGS_REGISTRY,
    ApplyTiming,
    SettingDefinition,
    SettingScope,
    UnregisteredSettingError,
    get_definition,
)

# Keys resolved through the per-user layer (scope USER).
USER_KEYS = {
    "DEFAULT_CURRENCY",
    "DEFAULT_DEVICE",
    "DEFAULT_LANDING_PAGE",
    "DEFAULT_PAGE_SIZE",
    "THEME",
    "DISPLAY_TIME_ZONE",
    "DATE_FORMAT_LOCALE",
    "DATETIME_FORMAT",
}

EXPECTED_KEYS = {
    *USER_KEYS,
    "TZ",
    "DEBUG",
    "SECRET_KEY",
    "APP_URL",
    "DEV_LOGIN_PREFILL",
    "ALLOWED_HOSTS",
    "DATA_DIR",
    "HASHED_STATIC",
}


def test_registry_has_exactly_the_expected_settings():
    assert set(SETTINGS_REGISTRY) == EXPECTED_KEYS


@pytest.mark.parametrize("meta_knob", ["ENV_FILE", "INI_FILE", "PROD"])
def test_meta_knobs_are_not_registered(meta_knob):
    assert meta_knob not in SETTINGS_REGISTRY


def test_scopes_and_timings():
    for key in USER_KEYS:
        definition = get_definition(key)
        assert definition.scope is SettingScope.USER
        assert definition.apply_timing is ApplyTiming.LIVE

    tz = get_definition("TZ")
    assert tz.scope is SettingScope.INFRA
    assert tz.apply_timing is ApplyTiming.RESTART
    assert tz.note  # display-only rationale documented

    for key in EXPECTED_KEYS - USER_KEYS:
        assert get_definition(key).scope is SettingScope.INFRA


def test_dev_login_prefill_must_stay_restart():
    # Regression pin: DEV_LOGIN_PREFILL is read from the boot-frozen settings
    # object and parsed through a value-keyed @lru_cache in games/dev_login.py,
    # so it must never become live-editable.
    assert get_definition("DEV_LOGIN_PREFILL").apply_timing is ApplyTiming.RESTART


def test_only_secret_key_uses_file_and_secret():
    for key in EXPECTED_KEYS:
        definition = get_definition(key)
        expected = key == "SECRET_KEY"
        assert definition.allow_file is expected
        assert definition.secret is expected


def test_every_definition_has_a_label():
    for key in EXPECTED_KEYS:
        assert get_definition(key).label


def test_env_name_defaults_to_key():
    for key in EXPECTED_KEYS:
        assert get_definition(key).env_name == key


def test_currency_validator_normalizes():
    validator = get_definition("DEFAULT_CURRENCY").validator
    assert validator is not None
    assert validator("eur") == "EUR"
    assert validator(" usd ") == "USD"


def test_theme_validator_accepts_only_supported_preferences():
    validator = get_definition("THEME").validator
    assert validator is not None
    assert validator("system") == "system"
    assert validator("light") == "light"
    assert validator("dark") == "dark"

    with pytest.raises(ValidationError):
        validator("sepia")
    with pytest.raises(ValidationError):
        validator("auto")


def test_theme_choices_use_the_final_shared_vocabulary():
    assert settings_registry.THEME_CHOICES == (
        ("system", "System"),
        ("light", "Light"),
        ("dark", "Dark"),
    )
    assert get_definition("THEME").default_factory() == "system"


def test_theme_model_field_fits_the_longest_preference():
    field = UserPreferences._meta.get_field("theme")

    assert field.max_length == 6
    assert tuple(field.choices) == settings_registry.THEME_CHOICES


def test_datetime_format_registry_contract():
    assert settings_registry.DATETIME_FORMAT_CHOICES == (
        ("iso_8601", "ISO 8601"),
        ("dmy_24h", "DD/MM/YYYY, 24-hour"),
        ("mdy_12h", "MM/DD/YYYY, 12-hour"),
    )

    definition = get_definition("DATETIME_FORMAT")
    assert definition.scope is SettingScope.USER
    assert definition.apply_timing is ApplyTiming.LIVE
    assert definition.widget == "select"
    assert definition.default_factory() == "iso_8601"


def test_datetime_format_model_field_is_nullable():
    field = UserPreferences._meta.get_field("datetime_format")

    assert field.null is True
    assert field.blank is True
    assert field.default is None


def test_datetime_format_validator_normalizes_case_and_outer_whitespace():
    validator = get_definition("DATETIME_FORMAT").validator
    assert validator is not None
    assert validator(" MDY_12H ") == "mdy_12h"


@pytest.mark.parametrize("bad", ["rfc_3339", "", 1, True])
def test_datetime_format_validator_rejects_unsupported_values(bad):
    validator = get_definition("DATETIME_FORMAT").validator
    assert validator is not None
    with pytest.raises(ValidationError):
        validator(bad)


@pytest.mark.parametrize("bad", ["EU", "EURO", "12$", "e1r", ""])
def test_currency_validator_rejects(bad):
    validator = get_definition("DEFAULT_CURRENCY").validator
    assert validator is not None
    with pytest.raises(ValidationError):
        validator(bad)


def test_landing_page_choices_are_the_supported_destinations():
    assert settings_registry.LANDING_PAGE_CHOICES == (
        ("games:list_sessions", "Sessions"),
        ("games:list_games", "Games"),
        ("games:list_purchases", "Purchases"),
        ("games:stats_by_year", "Statistics (this year)"),
    )


@pytest.mark.parametrize(
    "url_name",
    [
        "games:list_sessions",
        "games:list_games",
        "games:list_purchases",
        "games:stats_by_year",
    ],
)
def test_landing_page_validator_accepts_supported_url_names(url_name):
    validator = get_definition("DEFAULT_LANDING_PAGE").validator
    assert validator is not None
    assert validator(url_name) == url_name


@pytest.mark.parametrize(
    "bad", ["/stats", "games:stats_alltime", "https://example.com"]
)
def test_landing_page_validator_rejects_unsupported_destinations(bad):
    validator = get_definition("DEFAULT_LANDING_PAGE").validator
    assert validator is not None
    with pytest.raises(ValidationError):
        validator(bad)


@pytest.mark.parametrize("value", [10, 25, 50, 100, 500, 1000])
def test_page_size_validator_accepts_picker_choices(value):
    validator = get_definition("DEFAULT_PAGE_SIZE").validator
    assert validator is not None
    assert validator(value) == value


@pytest.mark.parametrize("bad", [True, 0, -1, 20, 1001, "lots"])
def test_page_size_validator_rejects_non_choices(bad):
    validator = get_definition("DEFAULT_PAGE_SIZE").validator
    assert validator is not None
    with pytest.raises(ValidationError):
        validator(bad)


def test_unregistered_key_raises():
    with pytest.raises(UnregisteredSettingError):
        get_definition("NOPE")


def test_definition_is_frozen():
    with pytest.raises(FrozenInstanceError):
        get_definition("DEBUG").cast = list  # type: ignore[misc]


def test_infra_setting_must_be_restart():
    with pytest.raises(ValueError):
        SettingDefinition(
            "X",
            scope=SettingScope.INFRA,
            apply_timing=ApplyTiming.LIVE,
            label="x",
            default_factory=lambda: None,
        )
