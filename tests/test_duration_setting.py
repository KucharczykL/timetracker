"""DURATION_FORMAT resolves through the same chain every user preference does."""

import pytest
from django.core.exceptions import ValidationError
from django.test import RequestFactory

from common.duration_presentation import duration_presentation_for_request
from timetracker.settings_commands import change_site_setting, change_user_setting
from timetracker.settings_resolver import resolve_str_for_user


@pytest.fixture
def user(django_user_model, db):
    return django_user_model.objects.create_user(username="u", password="p")


def test_default_is_decimal_hours(user):
    assert resolve_str_for_user(user, "DURATION_FORMAT") == "decimal_hours"


def test_personal_value_overrides_the_site_default(user):
    change_site_setting("DURATION_FORMAT", "whole_hours")
    change_user_setting(user, "DURATION_FORMAT", "adaptive")

    assert resolve_str_for_user(user, "DURATION_FORMAT") == "adaptive"


def test_clearing_the_personal_value_restores_the_site_default(user):
    change_site_setting("DURATION_FORMAT", "whole_hours")
    change_user_setting(user, "DURATION_FORMAT", "adaptive")

    change_user_setting(user, "DURATION_FORMAT", None)

    assert resolve_str_for_user(user, "DURATION_FORMAT") == "whole_hours"


@pytest.mark.parametrize("value", ["two_hours", "", "ADAPTIVE!"])
def test_unregistered_profile_is_rejected(user, value):
    with pytest.raises(ValidationError):
        change_user_setting(user, "DURATION_FORMAT", value)


def test_presentation_is_cached_on_the_request(user):
    request = RequestFactory().get("/tracker/session/list")
    request.user = user

    first = duration_presentation_for_request(request)
    second = duration_presentation_for_request(request)

    assert first is second
    assert first.profile.id == "decimal_hours"


def test_presentation_follows_the_personal_preference(user):
    change_user_setting(user, "DURATION_FORMAT", "adaptive")
    request = RequestFactory().get("/tracker/session/list")
    request.user = user

    assert duration_presentation_for_request(request).profile.id == "adaptive"
