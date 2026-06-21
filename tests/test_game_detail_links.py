"""Rendering tests: game-detail sections wire "View all" links to filtered lists (#66)."""

from datetime import datetime, timezone

import pytest
from django.utils.html import escape

from games.filters import (
    PlayEventFilter,
    PurchaseFilter,
    SessionFilter,
    filter_url,
)
from games.models import Game, Platform, PlayEvent, Purchase, Session
from games.views.game import view_game


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
