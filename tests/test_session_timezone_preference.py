"""The SESSION_TIME_ZONE_DISPLAY per-user preference: registry entry,
default, persistence through the bag, and validation."""

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from games.models import UserPreferences
from timetracker import settings_resolver
from timetracker.settings_commands import change_user_setting
from timetracker.settings_registry import (
    SETTINGS_REGISTRY,
    SettingScope,
    SettingWidget,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(username="tester", password="pw")


@pytest.fixture(autouse=True)
def _clear_resolver_cache():
    settings_resolver.clear_cache()
    yield
    settings_resolver.clear_cache()


def test_setting_is_registered_as_a_user_select():
    definition = SETTINGS_REGISTRY["SESSION_TIME_ZONE_DISPLAY"]
    assert definition.scope is SettingScope.USER
    assert definition.widget is SettingWidget.SELECT
    assert definition.choices == (
        ("account", "My current time zone"),
        ("own", "The session's own time zone"),
    )


def test_default_resolves_to_own(user):
    """Own-zone is the sensible default: an account-zone projection of a
    session logged abroad reads as a nonsensical time (a 21:00 session
    showing as 08:37) unless the user opts into it deliberately."""
    assert (
        settings_resolver.resolve_str_for_user(user, "SESSION_TIME_ZONE_DISPLAY")
        == "own"
    )


def test_change_persists_account_through_the_bag(user):
    change_user_setting(user, "SESSION_TIME_ZONE_DISPLAY", "account")
    settings_resolver.clear_cache()
    assert (
        settings_resolver.resolve_str_for_user(user, "SESSION_TIME_ZONE_DISPLAY")
        == "account"
    )
    preferences = UserPreferences.objects.get(user=user)
    assert preferences.extra_preferences["SESSION_TIME_ZONE_DISPLAY"] == "account"


def test_invalid_value_is_rejected(user):
    with pytest.raises(ValidationError):
        change_user_setting(user, "SESSION_TIME_ZONE_DISPLAY", "browser")
