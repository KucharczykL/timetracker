"""Rendering tests: game-detail sections wire "View all" links to filtered lists (#66)."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from django.urls import reverse
from django.utils.html import escape

from games.filters import (
    PlayEventFilter,
    PurchaseFilter,
    SessionFilter,
    filter_url,
)
from games.models import Game, Platform, PlayEvent, Purchase, Session
from games.views.game import view_game
from games.formatting import session_time_range
from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DateTimePresentation,
)

_PRESENTATION = DateTimePresentation(
    DEFAULT_DATE_TIME_FORMAT_PROFILE, "en-us", ZoneInfo("Europe/Prague")
)


def _dt(day, hour=12):
    return datetime(2024, 6, day, hour, 0, tzinfo=timezone.utc)


@pytest.fixture
def game(db):
    platform = Platform.objects.create(name="PC")
    game = Game.objects.create(
        name="Test Game", platform=platform, status=Game.Status.PLAYED
    )
    Session.objects.create(game=game, timestamp_start=_dt(1), timestamp_end=_dt(1, 13))
    Purchase.objects.create(date_purchased=_dt(1), type=Purchase.GAME).games.set([game])
    PlayEvent.objects.create(game=game, ended=_dt(2))
    return game


@pytest.fixture
def rendered(game, rf, django_user_model):
    user = django_user_model.objects.create_user(username="u", password="p")
    request = rf.get(f"/game/{game.id}/")
    request.user = user
    request.session = {}
    return view_game(request, game.id).content.decode()


def test_sessions_section_links_to_filtered_sessions(game, rendered):
    href = escape(filter_url(SessionFilter.where(game=[game.id])))
    assert href in rendered


def test_purchases_section_links_to_filtered_purchases(game, rendered):
    href = escape(filter_url(PurchaseFilter.where(games=[game.id])))
    assert href in rendered


def test_playevents_section_links_to_filtered_playevents(game, rendered):
    href = escape(filter_url(PlayEventFilter.where(game=[game.id])))
    assert href in rendered


def test_link_filters_scope_to_game(game):
    """Each link's filter selects exactly the game's own records, not another
    game's (parity between the section and the filtered list it links to)."""
    other = Game.objects.create(name="Other", platform=game.platform)
    Session.objects.create(game=other, timestamp_start=_dt(3), timestamp_end=_dt(3, 13))
    Purchase.objects.create(date_purchased=_dt(3), type=Purchase.GAME).games.set(
        [other]
    )
    PlayEvent.objects.create(game=other, ended=_dt(4))

    sessions = Session.objects.filter(SessionFilter.where(game=[game.id]).to_q())
    assert list(sessions) == list(game.sessions.all())

    purchases = Purchase.objects.filter(PurchaseFilter.where(games=[game.id]).to_q())
    assert list(purchases) == list(game.purchases.all())

    playevents = PlayEvent.objects.filter(PlayEventFilter.where(game=[game.id]).to_q())
    assert list(playevents) == list(game.playevents.all())


def test_game_header_has_log_this_game_link(game, rendered):
    """The start-session affordance lives in the game header (#55)."""
    href = reverse("games:add_session_for_game", kwargs={"game_id": game.id})
    assert href in rendered
    assert "Log this game" in rendered


def test_sessions_section_is_read_only(game, rendered):
    """Game-detail sessions table is plain data: no interactive row swap, no
    per-row action buttons, no section-header add/resume buttons (#55)."""
    session = game.sessions.first()
    # No canonical interactive list row (id + htmx device-changed swap)
    assert "session-row-" not in rendered
    assert "device-changed" not in rendered
    # No per-row edit/delete session actions
    assert reverse("games:edit_session", args=[session.pk]) not in rendered
    assert reverse("games:delete_session", args=[session.pk]) not in rendered
    # No section-header resume button. Scope to the page body: the navbar's log
    # dropdown legitimately carries per-game resume links (#419), which are
    # chrome, not part of this read-only section.
    body = rendered.split("</nav>", 1)[-1]
    assert "/session/add/from-list/" not in body
    # Device shown as a plain column (the column header, not an incidental match)
    assert ">Device<" in rendered


def test_sessions_section_shows_last_five(db, django_user_model, rf):
    """Only the five most-recent sessions render; the badge keeps the total."""
    platform = Platform.objects.create(name="PC")
    many = Game.objects.create(name="Many", platform=platform)
    sessions = [
        Session.objects.create(
            game=many, timestamp_start=_dt(day), timestamp_end=_dt(day, 13)
        )
        for day in range(1, 7)  # six sessions, days 1..6
    ]
    user = django_user_model.objects.create_user(username="many", password="p")
    request = rf.get(f"/game/{many.id}/")
    request.user = user
    request.session = {}
    html = view_game(request, many.id).content.decode()

    newest, oldest = sessions[-1], sessions[0]
    # session_time_range output (digits/spaces/em-dash) isn't HTML-escaped, so no escape() needed
    assert session_time_range(newest, _PRESENTATION) in html  # day 6 shown
    assert session_time_range(oldest, _PRESENTATION) not in html  # day 1 dropped


def test_no_view_all_for_empty_section(db, django_user_model, rf):
    """A game with no sessions/purchases/playevents shows no 'View all' link."""
    platform = Platform.objects.create(name="PC")
    empty_game = Game.objects.create(name="Empty", platform=platform)
    user = django_user_model.objects.create_user(username="u2", password="p")
    request = rf.get(f"/game/{empty_game.id}/")
    request.user = user
    request.session = {}
    html = view_game(request, empty_game.id).content.decode()
    assert "View all" not in html
