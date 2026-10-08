"""The browser suite takes the shared fixtures."""

import pytest


@pytest.mark.parametrize(
    "fixture",
    [
        "_fast_password_hashing",
        "_process_clock_off_the_calendar",
        "_reset_settings_caches",
        "_track_created_games",
        "chunk_queue",
        "unknown_icon_names_fail",
    ],
)
def test_the_shared_fixtures_apply(request, fixture):
    assert fixture in request.fixturenames
