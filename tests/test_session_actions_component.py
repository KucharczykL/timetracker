"""Session row actions: finish posts, reset confirms on its own page."""

from datetime import UTC, datetime

import pytest
from django.urls import reverse

from common.components import SessionActions
from games.models import Game, Platform, Session

STARTED_AT = datetime(2024, 6, 1, 12, tzinfo=UTC)


@pytest.fixture
def open_session(owned_library):
    game = Game.objects.create(
        library=owned_library,
        name="Test Game",
        platform=Platform.objects.create(name="PC"),
    )
    return Session.objects.create(game=game, timestamp_start=STARTED_AT)


@pytest.fixture
def finished_session(owned_library):
    game = Game.objects.create(
        library=owned_library,
        name="Done Game",
        platform=Platform.objects.create(name="Console"),
    )
    return Session.objects.create(
        game=game,
        timestamp_start=STARTED_AT,
        timestamp_end=datetime(2024, 6, 1, 14, tzinfo=UTC),
    )


def _render(session, origin=None) -> str:
    return str(SessionActions(session, "token", origin))


def test_open_session_renders_a_finish_post_form(open_session):
    origin = reverse("games:list_sessions")
    rendered = _render(open_session, origin)

    assert 'method="post"' in rendered
    assert reverse("games:finish_session", args=[open_session.pk]) in rendered
    assert "origin=" in rendered


def test_reset_is_a_link_to_the_confirmation_page(open_session):
    rendered = _render(open_session)

    assert reverse("games:reset_session", args=[open_session.pk]) in rendered


def test_finished_session_renders_neither_finish_nor_reset(finished_session):
    rendered = _render(finished_session)

    assert reverse("games:finish_session", args=[finished_session.pk]) not in rendered
    assert reverse("games:reset_session", args=[finished_session.pk]) not in rendered
    assert reverse("games:edit_session", args=[finished_session.pk]) in rendered


def test_no_reset_modal_markup_is_emitted(open_session):
    rendered = _render(open_session)

    assert "data-reset-modal" not in rendered
    assert "data-reset-confirm" not in rendered
    assert "data-finish" not in rendered


def test_browser_time_zone_input_rides_on_the_finish_form(open_session):
    rendered = _render(open_session)

    assert "<browser-time-zone" in rendered
    assert 'name="browser_time_zone"' in rendered


def test_actions_no_longer_reference_the_session_api(open_session):
    rendered = _render(open_session)

    assert "/api/session/" not in rendered
    assert "session-actions" not in rendered
