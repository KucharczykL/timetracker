"""Tests for the per-user layer of the settings resolver (Stage 2).

The user layer sits above the shared chain: a personal value wins over env, the
site DB row, and the code default. Unset (NULL column / absent JSON key) falls
through. Mirrors the fixtures/patterns of ``test_settings_resolver.py``.
"""

import pytest
from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import override_settings

from timetracker import config as config_module
from timetracker import settings_resolver
from timetracker.config import SettingSource
from timetracker.settings_commands import change_site_setting
from timetracker.settings_resolver import (
    resolve_for_user,
    resolve_for_user_with_origin,
    set_user_preference,
)


@pytest.fixture
def no_currency_env(monkeypatch):
    monkeypatch.delenv("DEFAULT_CURRENCY", raising=False)
    monkeypatch.delenv("DEFAULT_CURRENCY__FILE", raising=False)
    config_module.reset_caches()
    settings_resolver.clear_cache()
    yield


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(username="tester", password="pw")


@pytest.fixture
def other_user(db):
    return get_user_model().objects.create_user(username="other", password="pw")


def _write_currency_row(django_capture_on_commit_callbacks, value):
    with django_capture_on_commit_callbacks(execute=True):
        change_site_setting("DEFAULT_CURRENCY", value)


def _set_user(django_capture_on_commit_callbacks, user, key, value):
    with django_capture_on_commit_callbacks(execute=True):
        set_user_preference(user, key, value)


@pytest.fixture
def no_datetime_format_env(monkeypatch, tmp_path):
    monkeypatch.delenv("DATETIME_FORMAT", raising=False)
    # Isolate the shared chain from repository/developer config files. Pointing
    # both locators at known-missing paths also prevents the default .env and
    # settings.ini locations from being consulted.
    monkeypatch.setenv("ENV_FILE", str(tmp_path / "missing.env"))
    monkeypatch.setenv("INI_FILE", str(tmp_path / "missing.ini"))
    config_module.reset_caches()
    settings_resolver.clear_cache()
    yield


# --- precedence -----------------------------------------------------------


def test_user_beats_site_beats_default(
    user, no_currency_env, django_capture_on_commit_callbacks
):
    _write_currency_row(django_capture_on_commit_callbacks, "USD")
    _set_user(django_capture_on_commit_callbacks, user, "DEFAULT_CURRENCY", "EUR")
    result = resolve_for_user_with_origin(user, "DEFAULT_CURRENCY")
    assert result.value == "EUR"
    assert result.source is SettingSource.USER
    assert result.locked is False


def test_unset_user_falls_through_to_site(
    user, no_currency_env, django_capture_on_commit_callbacks
):
    _write_currency_row(django_capture_on_commit_callbacks, "USD")
    result = resolve_for_user_with_origin(user, "DEFAULT_CURRENCY")
    assert result.value == "USD"
    assert result.source is SettingSource.DATABASE


def test_unset_everything_falls_through_to_default(user, no_currency_env):
    result = resolve_for_user_with_origin(user, "DEFAULT_CURRENCY")
    assert result.value == django_settings.DEFAULT_CURRENCY
    assert result.source is SettingSource.DEFAULT


@override_settings(TIME_ZONE="Pacific/Kiritimati")
def test_display_time_zone_defaults_to_utc(user):
    settings_resolver.clear_cache()
    result = resolve_for_user_with_origin(user, "DISPLAY_TIME_ZONE")
    assert result.value == "UTC"
    assert result.source is SettingSource.DEFAULT


def test_datetime_format_defaults_to_iso_8601(user, no_datetime_format_env):
    result = resolve_for_user_with_origin(user, "DATETIME_FORMAT")
    assert result.value == "iso_8601"
    assert result.source is SettingSource.DEFAULT


def test_anonymous_user_datetime_format_defaults_to_iso_8601(
    db, no_datetime_format_env
):
    from django.contrib.auth.models import AnonymousUser

    result = resolve_for_user_with_origin(AnonymousUser(), "DATETIME_FORMAT")
    assert result.value == "iso_8601"
    assert result.source is SettingSource.DEFAULT


def test_datetime_format_personal_clear_inherits_site_default(
    user, no_datetime_format_env, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        change_site_setting("DATETIME_FORMAT", "dmy_24h")
    _set_user(django_capture_on_commit_callbacks, user, "DATETIME_FORMAT", "mdy_12h")
    _set_user(django_capture_on_commit_callbacks, user, "DATETIME_FORMAT", None)

    result = resolve_for_user_with_origin(user, "DATETIME_FORMAT")
    assert (result.value, result.source) == (
        "dmy_24h",
        SettingSource.DATABASE,
    )


def test_datetime_format_personal_override_beats_environment(
    user,
    monkeypatch,
    no_datetime_format_env,
    django_capture_on_commit_callbacks,
):
    monkeypatch.setenv("DATETIME_FORMAT", "dmy_24h")
    config_module.reset_caches()
    _set_user(django_capture_on_commit_callbacks, user, "DATETIME_FORMAT", "mdy_12h")

    result = resolve_for_user_with_origin(user, "DATETIME_FORMAT")
    assert (result.value, result.source) == ("mdy_12h", SettingSource.USER)


def test_datetime_format_environment_beats_site_default(
    user,
    monkeypatch,
    no_datetime_format_env,
    django_capture_on_commit_callbacks,
):
    with django_capture_on_commit_callbacks(execute=True):
        change_site_setting("DATETIME_FORMAT", "dmy_24h")
    monkeypatch.setenv("DATETIME_FORMAT", "mdy_12h")
    config_module.reset_caches()

    result = resolve_for_user_with_origin(user, "DATETIME_FORMAT")
    assert (result.value, result.source, result.locked) == (
        "mdy_12h",
        SettingSource.ENV,
        True,
    )


def test_datetime_format_ini_beats_site_default_and_normalizes(
    user,
    monkeypatch,
    tmp_path,
    no_datetime_format_env,
    django_capture_on_commit_callbacks,
):
    with django_capture_on_commit_callbacks(execute=True):
        change_site_setting("DATETIME_FORMAT", "dmy_24h")
    ini_path = tmp_path / "datetime-format.ini"
    ini_path.write_text("[timetracker]\nDATETIME_FORMAT = MDY_12H\n")
    monkeypatch.setenv("INI_FILE", str(ini_path))
    config_module.reset_caches()

    result = resolve_for_user_with_origin(user, "DATETIME_FORMAT")
    assert (result.value, result.source, result.locked) == (
        "mdy_12h",
        SettingSource.INI,
        True,
    )


def test_user_beats_env(
    user, monkeypatch, no_currency_env, django_capture_on_commit_callbacks
):
    # Env-locking per-user prefs is deferred, so a personal value wins over env.
    _set_user(django_capture_on_commit_callbacks, user, "DEFAULT_CURRENCY", "EUR")
    monkeypatch.setenv("DEFAULT_CURRENCY", "USD")
    config_module.reset_caches()
    result = resolve_for_user_with_origin(user, "DEFAULT_CURRENCY")
    assert result.value == "EUR"
    assert result.source is SettingSource.USER


def test_clearing_reverts_to_site(
    user, no_currency_env, django_capture_on_commit_callbacks
):
    _write_currency_row(django_capture_on_commit_callbacks, "USD")
    _set_user(django_capture_on_commit_callbacks, user, "DEFAULT_CURRENCY", "EUR")
    assert resolve_for_user(user, "DEFAULT_CURRENCY") == "EUR"
    _set_user(django_capture_on_commit_callbacks, user, "DEFAULT_CURRENCY", None)
    result = resolve_for_user_with_origin(user, "DEFAULT_CURRENCY")
    assert result.value == "USD"
    assert result.source is SettingSource.DATABASE


def test_scoping_between_users(
    user, other_user, no_currency_env, django_capture_on_commit_callbacks
):
    _set_user(django_capture_on_commit_callbacks, user, "DEFAULT_CURRENCY", "EUR")
    assert resolve_for_user(user, "DEFAULT_CURRENCY") == "EUR"
    # other_user has no override, so resolves the default, not EUR.
    result = resolve_for_user_with_origin(other_user, "DEFAULT_CURRENCY")
    assert result.value == django_settings.DEFAULT_CURRENCY
    assert result.source is SettingSource.DEFAULT


def test_anonymous_user_uses_shared_chain(
    db, no_currency_env, django_capture_on_commit_callbacks
):
    from django.contrib.auth.models import AnonymousUser

    _write_currency_row(django_capture_on_commit_callbacks, "USD")
    result = resolve_for_user_with_origin(AnonymousUser(), "DEFAULT_CURRENCY")
    assert result.value == "USD"
    assert result.source is SettingSource.DATABASE


def test_non_user_scope_proxies_to_shared_chain(user, monkeypatch):
    # A non-USER key routes straight through, so callers can use one entry point.
    monkeypatch.delenv("TZ", raising=False)
    config_module.reset_caches()
    settings_resolver.clear_cache()
    result = resolve_for_user_with_origin(user, "TZ")
    assert result.value == django_settings.TIME_ZONE
    assert result.source is SettingSource.DEFAULT


# --- typed columns other than currency ------------------------------------


def test_device_pref_round_trips_as_id(user, db, django_capture_on_commit_callbacks):
    from games.models import Device

    device = Device.objects.create(name="Deck", type=Device.HANDHELD)
    _set_user(django_capture_on_commit_callbacks, user, "DEFAULT_DEVICE", device.pk)
    result = resolve_for_user_with_origin(user, "DEFAULT_DEVICE")
    assert result.value == device.pk
    assert result.source is SettingSource.USER


def test_landing_page_pref_round_trips(user, db, django_capture_on_commit_callbacks):
    _set_user(
        django_capture_on_commit_callbacks,
        user,
        "DEFAULT_LANDING_PAGE",
        "games:stats_by_year",
    )
    assert resolve_for_user(user, "DEFAULT_LANDING_PAGE") == "games:stats_by_year"


def test_theme_pref_round_trips_through_typed_column(
    user, db, django_capture_on_commit_callbacks
):
    from games.models import UserPreferences

    _set_user(django_capture_on_commit_callbacks, user, "THEME", "dark")

    preferences = UserPreferences.objects.get(user=user)
    assert preferences.theme == "dark"
    assert resolve_for_user(user, "THEME") == "dark"


def test_presentation_preferences_round_trip_through_typed_columns(
    user, django_capture_on_commit_callbacks
):
    from games.models import UserPreferences

    _set_user(
        django_capture_on_commit_callbacks,
        user,
        "DISPLAY_TIME_ZONE",
        " Europe/Prague ",
    )
    _set_user(
        django_capture_on_commit_callbacks,
        user,
        "DATE_FORMAT_LOCALE",
        " CS ",
    )

    preferences = UserPreferences.objects.get(user=user)
    assert preferences.display_time_zone == "Europe/Prague"
    assert preferences.date_format_locale == "cs"
    assert resolve_for_user(user, "DISPLAY_TIME_ZONE") == "Europe/Prague"
    assert resolve_for_user(user, "DATE_FORMAT_LOCALE") == "cs"


@pytest.mark.parametrize("value", ["ISO 8601", "rfc_3339", "", 1, True])
def test_datetime_format_rejects_unsupported_values(user, value):
    from games.models import UserPreferences

    with pytest.raises(ValidationError):
        set_user_preference(user, "DATETIME_FORMAT", value)

    assert not UserPreferences.objects.filter(user=user).exists()


def test_user_prefs_admin_form_normalizes_datetime_format(db):
    from games.admin import UserPreferencesForm

    user = get_user_model().objects.create_user(username="admin-pref")
    form = UserPreferencesForm(
        data={
            "user": user.pk,
            "datetime_format": " MDY_12H ",
            "extra_preferences": "{}",
        }
    )

    assert form.is_valid(), form.errors
    assert form.save().datetime_format == "mdy_12h"


def test_user_prefs_admin_form_blank_datetime_format_saves_null(db):
    from games.admin import UserPreferencesForm

    user = get_user_model().objects.create_user(username="admin-clear")
    form = UserPreferencesForm(
        data={
            "user": user.pk,
            "datetime_format": "",
            "extra_preferences": "{}",
        }
    )

    assert form.is_valid(), form.errors
    assert form.save().datetime_format is None


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("DISPLAY_TIME_ZONE", "Mars/Olympus"),
        ("DATE_FORMAT_LOCALE", "de-de"),
    ],
)
def test_presentation_preferences_reject_unsupported_values(user, key, value):
    from games.models import UserPreferences

    with pytest.raises(ValidationError):
        set_user_preference(user, key, value)

    assert not UserPreferences.objects.filter(user=user).exists()


# --- poison value / robustness --------------------------------------------


def test_poison_user_value_degrades_to_shared_chain(
    user, no_currency_env, django_capture_on_commit_callbacks, capture_games_logger
):
    from games.models import UserPreferences

    _write_currency_row(django_capture_on_commit_callbacks, "USD")
    # An invalid value can only reach the column via raw update() bypassing
    # normalize; it must not crash resolve — degrade to the site/default layers.
    UserPreferences.objects.create(user=user)
    UserPreferences.objects.filter(user=user).update(default_currency="EURO")
    settings_resolver.clear_cache()
    with capture_games_logger():
        result = resolve_for_user_with_origin(user, "DEFAULT_CURRENCY")
    assert result.value == "USD"
    assert result.source is SettingSource.DATABASE


# --- write guards ---------------------------------------------------------


def test_set_user_preference_rejects_unknown_key(user, db):
    with pytest.raises(KeyError):
        set_user_preference(user, "NOPE", "x")


def test_set_user_preference_rejects_non_user_key(user, db):
    with pytest.raises(ValueError):
        set_user_preference(user, "TZ", "Europe/Prague")


def test_set_user_preference_rejects_invalid_and_writes_nothing(user, db):
    from games.models import UserPreferences

    with pytest.raises(ValidationError):
        set_user_preference(user, "DEFAULT_CURRENCY", "EURO")
    assert not UserPreferences.objects.filter(user=user).exists()


def test_set_user_preference_rejects_missing_device(user, db):
    from games.models import UserPreferences

    with pytest.raises(ValidationError):
        set_user_preference(user, "DEFAULT_DEVICE", 9999)
    assert not UserPreferences.objects.filter(user=user).exists()


def test_get_for_user_is_idempotent(user, db):
    from games.models import UserPreferences

    first = UserPreferences.get_for_user(user)
    second = UserPreferences.get_for_user(user)
    assert first.pk == second.pk
    assert UserPreferences.objects.filter(user=user).count() == 1


# --- cache ----------------------------------------------------------------


def test_user_snapshot_invalidated_on_write(
    user, no_currency_env, django_capture_on_commit_callbacks
):
    # Warm with the empty (default) state.
    assert resolve_for_user_with_origin(user, "DEFAULT_CURRENCY").source is (
        SettingSource.DEFAULT
    )
    _set_user(django_capture_on_commit_callbacks, user, "DEFAULT_CURRENCY", "EUR")
    # on_commit invalidation ran → immediate, no TTL wait.
    result = resolve_for_user_with_origin(user, "DEFAULT_CURRENCY")
    assert result.value == "EUR"
    assert result.source is SettingSource.USER


def test_user_queryset_update_is_invisible_until_ttl(
    user, no_currency_env, monkeypatch
):
    from games.models import UserPreferences

    clock = {"now": 1000.0}
    monkeypatch.setattr(settings_resolver.time, "monotonic", lambda: clock["now"])
    UserPreferences.objects.create(user=user, default_currency="EUR")
    settings_resolver.clear_cache()
    assert resolve_for_user(user, "DEFAULT_CURRENCY") == "EUR"  # warms at t=1000
    # Raw update bypasses signals; stale until the TTL lapses.
    UserPreferences.objects.filter(user=user).update(default_currency="GBP")
    assert resolve_for_user(user, "DEFAULT_CURRENCY") == "EUR"
    clock["now"] += settings_resolver.SITE_SETTINGS_TTL_SECONDS + 1
    assert resolve_for_user(user, "DEFAULT_CURRENCY") == "GBP"


def test_clear_cache_drops_user_snapshot(user, no_currency_env):
    from games.models import UserPreferences

    UserPreferences.objects.create(user=user, default_currency="EUR")
    settings_resolver.clear_cache()
    assert resolve_for_user(user, "DEFAULT_CURRENCY") == "EUR"  # warms snapshot
    UserPreferences.objects.filter(user=user).update(default_currency="GBP")
    settings_resolver.clear_cache()
    assert resolve_for_user(user, "DEFAULT_CURRENCY") == "GBP"
