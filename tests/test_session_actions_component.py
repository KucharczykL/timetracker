"""The session row's menu: what each row offers, and in what order."""

import re
from datetime import UTC, datetime, timedelta

import pytest
from django.urls import reverse
from session_rows import corrected_row, duration_only_row, session_row, tracked_run

from games.bulk_move import MOVE
from games.models import Game, Platform
from games.views.session_menu import session_row_menu

STARTED_AT = datetime(2024, 6, 1, 12, tzinfo=UTC)
A_DAY = datetime(2024, 6, 1, tzinfo=UTC).date()

pytestmark = pytest.mark.django_db


@pytest.fixture
def open_session(owned_library):
    game = Game.objects.create(
        library=owned_library,
        name="Test Game",
        platform=Platform.objects.create(name="PC"),
    )
    return session_row(game, started_at=STARTED_AT)


@pytest.fixture
def finished_session(owned_library):
    game = Game.objects.create(
        library=owned_library,
        name="Done Game",
        platform=Platform.objects.create(name="Console"),
    )
    return session_row(
        game, started_at=STARTED_AT, ended_at=datetime(2024, 6, 1, 14, tzinfo=UTC)
    )


@pytest.fixture
def corrected_session(owned_library):
    """States both instants and a duration: never running."""
    game = Game.objects.create(library=owned_library, name="Corrected Game")
    return corrected_row(
        tracked_run(owned_library, game),
        STARTED_AT,
        datetime(2024, 6, 1, 14, tzinfo=UTC),
        timedelta(hours=3),
    )


@pytest.fixture
def written_session(owned_library):
    """Duration-only: hours a person wrote down, not a sitting."""
    game = Game.objects.create(library=owned_library, name="Written Game")
    return duration_only_row(
        tracked_run(owned_library, game), A_DAY, timedelta(hours=9)
    )


def _render(session, origin=None) -> str:
    return str(session_row_menu(session, "token", origin))


def _items(rendered: str) -> list[str]:
    """Each item's own words, in the order the panel states them."""
    return [
        re.sub(r"<[^>]+>", "", found).strip()
        for found in re.findall(
            r'<(?:a|button)[^>]*role="menuitem"[^>]*>(.*?)</(?:a|button)>',
            rendered,
            re.DOTALL,
        )
    ]


def test_a_running_row_offers_five_acts_in_order(open_session):
    assert _items(_render(open_session)) == [
        "Finish",
        "Reset start to now",
        "Edit",
        MOVE.label,
        "Remove",
    ]


def test_a_finished_row_offers_neither_finish_nor_reset(finished_session):
    assert _items(_render(finished_session)) == ["Edit", MOVE.label, "Remove"]
    rendered = _render(finished_session)
    assert reverse("games:finish_session", args=[finished_session.pk]) not in rendered
    assert reverse("games:reset_session", args=[finished_session.pk]) not in rendered


def test_a_corrected_row_offers_neither_finish_nor_reset(corrected_session):
    assert _items(_render(corrected_session)) == ["Edit", MOVE.label, "Remove"]


def test_a_written_row_offers_the_record_act_and_a_measured_one_does_not(
    written_session, open_session
):
    #: Three dots: the form asks when the hours were played and where they
    #: came from, where Remove and Reset only have you confirm.
    assert _items(_render(written_session)) == [
        "Edit",
        MOVE.label,
        "Record as historical playtime\u2026",
        "Remove",
    ]
    assert "Record as historical playtime\u2026" not in _items(_render(open_session))


def test_finish_posts_to_its_own_route_carrying_the_browser_zone(open_session):
    origin = reverse("games:list_sessions")
    rendered = _render(open_session, origin)

    assert 'method="post"' in rendered
    assert reverse("games:finish_session", args=[open_session.pk]) in rendered
    assert "origin=" in rendered
    assert "<browser-time-zone" in rendered
    assert 'name="browser_time_zone"' in rendered


def test_move_hands_one_row_to_the_runner(open_session):
    rendered = _render(open_session)

    assert reverse("games:run_bulk_action", args=[MOVE.name]) in rendered
    assert (
        f"{{&quot;mode&quot;: &quot;some&quot;, &quot;keys&quot;: [&quot;{open_session.pk}&quot;]}}"
        in rendered
    )


def test_every_other_act_is_a_link_to_its_confirmation(written_session):
    rendered = _render(written_session, reverse("games:list_sessions"))

    for route in (
        "games:edit_session",
        "games:reclassify_session",
        "games:remove_session",
    ):
        assert reverse(route, args=[written_session.pk]) in rendered


def test_the_menu_names_its_row_rather_than_the_table(open_session):
    """The day as well as the game: one game can hold every row."""
    rendered = _render(open_session)

    assert f'id="session-menu-{open_session.pk}"' in rendered
    assert f"Test Game, {open_session.effective_day} actions" in rendered


def test_the_menu_references_no_session_api(open_session):
    rendered = _render(open_session)

    assert "/api/session/" not in rendered


def _items_markup(rendered: str) -> list[str]:
    """Each item's whole markup, in panel order."""
    return re.findall(
        r'<(?:a|button)[^>]*role="menuitem".*?</(?:a|button)>', rendered, re.DOTALL
    )


def test_every_item_leads_with_the_glyph_its_button_had(open_session):
    """The glyph is how a reader who knows the row finds the act."""
    items = _items_markup(_render(open_session))

    assert len(items) == 5
    for item in items:
        assert "<svg" in item, item[:120]
