"""Rendering tests: stats page wires rows/counts to filtered-list links (#65)."""

from datetime import datetime, timedelta, timezone

import pytest
from django.utils.html import escape

from games.filters import filter_url
from games.models import Game, Platform, PlayEvent, Purchase, Session
from games.views import stats_links
from games.views.stats_content import stats_content
from games.views.stats_data import compute_stats

YEAR = 2024


def _dt(month, day, hour=12):
    return datetime(YEAR, month, day, hour, 0, tzinfo=timezone.utc)


@pytest.fixture
def rendered(db):
    pc = Platform.objects.create(name="PC")
    # 6 games each played in-year → games-by-playtime exceeds the cap of 5.
    games = []
    for index in range(6):
        game = Game.objects.create(
            name=f"Game {index}", platform=pc, status=Game.Status.PLAYED
        )
        start = _dt(6, index + 1)
        Session.objects.create(
            game=game,
            timestamp_start=start,
            timestamp_end=start + timedelta(hours=index + 1),
        )
        games.append(game)

    abandoned = Game.objects.create(
        name="Abandoned", platform=pc, status=Game.Status.ABANDONED
    )
    Purchase.objects.create(date_purchased=_dt(1, 5), type=Purchase.GAME).games.set(
        [games[0]]
    )
    Purchase.objects.create(date_purchased=_dt(2, 5), type=Purchase.GAME).games.set(
        [abandoned]
    )  # dropped
    Purchase.objects.create(
        date_purchased=_dt(3, 5), date_refunded=_dt(4, 5), type=Purchase.GAME
    ).games.set([games[1]])  # refunded
    Purchase.objects.create(date_purchased=_dt(5, 5), type=Purchase.GAME).games.set(
        [games[2]]
    )  # unfinished

    finished_game = games[0]
    PlayEvent.objects.create(game=finished_game, ended=_dt(8, 1))

    ctx = compute_stats(YEAR)
    return {"html": str(stats_content(ctx)), "pc": pc, "games": games}


def _href(builder_filter, **extra):
    return escape(filter_url(builder_filter, **extra))


def test_total_count_links_to_purchases(rendered):
    assert _href(stats_links.purchases_total(YEAR)) in rendered["html"]


def test_refunded_count_links_to_refunded_purchases(rendered):
    assert _href(stats_links.purchases_refunded(YEAR)) in rendered["html"]


def test_dropped_count_links_to_dropped_purchases(rendered):
    assert _href(stats_links.purchases_dropped(YEAR)) in rendered["html"]


def test_unfinished_count_links_to_unfinished_purchases(rendered):
    assert _href(stats_links.purchases_unfinished(YEAR)) in rendered["html"]


def test_platform_row_links_to_platform_sessions(rendered):
    url = _href(stats_links.sessions_for_platform(rendered["pc"].id, YEAR))
    assert url in rendered["html"]


def test_game_row_has_session_link(rendered):
    # at least one games-by-playtime game links to its sessions
    any_game = rendered["games"][0]
    url = _href(stats_links.sessions_for_game(any_game.id, YEAR))
    assert url in rendered["html"]


def test_games_by_playtime_capped_with_view_all(rendered):
    # 6 games played, capped to 5 → a "View all" link to games_played
    assert "View all" in rendered["html"]
    view_all = filter_url(stats_links.games_played(YEAR), sort="-playtime")
    # the filter portion (before &sort) must be present even after attr-escaping
    assert escape(view_all.split("&")[0]) in rendered["html"]


def test_all_purchases_section_removed(rendered):
    assert "All Purchases" not in rendered["html"]


def test_generated_links_resolve_to_200(rendered, client, django_user_model):
    """A stats link, when visited, returns 200 with its filter applied."""
    user = django_user_model.objects.create_user(username="u", password="p")
    client.force_login(user)
    for builder in (
        stats_links.purchases_total(YEAR),
        stats_links.purchases_dropped(YEAR),
        stats_links.sessions_for_platform(rendered["pc"].id, YEAR),
    ):
        response = client.get(filter_url(builder), follow=True)
        assert response.status_code == 200
