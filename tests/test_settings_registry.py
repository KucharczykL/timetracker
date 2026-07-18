"""Tests for the declarative settings registry (no DB access)."""

from dataclasses import FrozenInstanceError

import pytest
from django.core.exceptions import ValidationError

from timetracker.settings_registry import (
    SETTINGS_REGISTRY,
    ApplyTiming,
    SettingDefinition,
    SettingScope,
    UnregisteredSettingError,
    get_definition,
)

EXPECTED_KEYS = {
    "DEFAULT_CURRENCY",
    "TZ",
    "DEBUG",
    "SECRET_KEY",
    "APP_URL",
    "DEV_LOGIN_PREFILL",
    "ALLOWED_HOSTS",
    "DATA_DIR",
    "HASHED_STATIC",
}


def test_registry_has_exactly_the_nine_settings():
    assert set(SETTINGS_REGISTRY) == EXPECTED_KEYS


@pytest.mark.parametrize("meta_knob", ["ENV_FILE", "INI_FILE", "PROD"])
def test_meta_knobs_are_not_registered(meta_knob):
    assert meta_knob not in SETTINGS_REGISTRY


def test_scopes_and_timings():
    currency = get_definition("DEFAULT_CURRENCY")
    assert currency.scope is SettingScope.SITE
    assert currency.apply_timing is ApplyTiming.LIVE

    tz = get_definition("TZ")
    assert tz.scope is SettingScope.INFRA
    assert tz.apply_timing is ApplyTiming.RESTART
    assert tz.note  # display-only rationale documented

    for key in EXPECTED_KEYS - {"DEFAULT_CURRENCY"}:
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


@pytest.mark.parametrize("bad", ["EU", "EURO", "12$", "e1r", ""])
def test_currency_validator_rejects(bad):
    validator = get_definition("DEFAULT_CURRENCY").validator
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
