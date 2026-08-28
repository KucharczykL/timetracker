"""ATOMIC_REQUESTS would make every dispatch raise."""

from django.test import override_settings

from games.checks import check_atomic_requests


def test_no_error_when_no_alias_wraps_a_request():
    assert check_atomic_requests() == []


def test_a_wrapped_alias_is_refused(settings):
    wrapped = {
        alias: {**config, "ATOMIC_REQUESTS": True}
        for alias, config in settings.DATABASES.items()
    }
    with override_settings(DATABASES=wrapped):
        errors = check_atomic_requests()

    assert [error.id for error in errors] == ["games.E008"]
    assert "default" in errors[0].msg
