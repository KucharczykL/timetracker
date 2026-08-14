"""Rendering tests: stats page wires rows/counts to filtered-list links (#65)."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth import get_user_model
from django.utils.html import escape

from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DateTimePresentation,
)
from common.duration_presentation import (
    DEFAULT_DURATION_FORMAT_PROFILE,
    DurationPresentation,
)
from games.filters import filter_url
from games.models import Game, Platform, PlayEvent, Purchase, Session
from games.views import stats_links
from games.views.stats_content import stats_content as _stats_content
from games.views.stats_data import compute_stats

YEAR = 2024
_PRESENTATION = DateTimePresentation(
    DEFAULT_DATE_TIME_FORMAT_PROFILE, "en-us", ZoneInfo("UTC")
)


_DURATIONS = DurationPresentation(DEFAULT_DURATION_FORMAT_PROFILE, "en-us")


def stats_content(ctx):
    return _stats_content(ctx, _PRESENTATION, _DURATIONS)


def _dt(month, day, hour=12):
    return datetime(YEAR, month, day, hour, 0, tzinfo=UTC)


@pytest.fixture
def rendered(db):
    library = get_user_model().objects.create_user(username="stats-content").library
    pc = Platform.objects.create(name="PC")
    # 6 games each played in-year → games-by-playtime exceeds the cap of 5.
    games = []
    for index in range(6):
        game = Game.objects.create(
            library=library,
            name=f"Game {index}",
            platform=pc,
            status=Game.Status.PLAYED,
        )
        start = _dt(6, index + 1)
        Session.objects.create(
            game=game,
            timestamp_start=start,
            timestamp_end=start + timedelta(hours=index + 1),
        )
        games.append(game)

    abandoned = Game.objects.create(
        library=library,
        name="Abandoned",
        platform=pc,
        status=Game.Status.ABANDONED,
    )
    Purchase.objects.create(
        library=library,
        price_currency="CZK",
        date_purchased=_dt(1, 5),
        type=Purchase.GAME,
    ).games.set([games[0]])
    Purchase.objects.create(
        library=library,
        price_currency="CZK",
        date_purchased=_dt(2, 5),
        type=Purchase.GAME,
    ).games.set([abandoned])  # dropped
    Purchase.objects.create(
        library=library,
        price_currency="CZK",
        date_purchased=_dt(3, 5),
        date_refunded=_dt(4, 5),
        type=Purchase.GAME,
    ).games.set([games[1]])  # refunded
    Purchase.objects.create(
        library=library,
        price_currency="CZK",
        date_purchased=_dt(5, 5),
        type=Purchase.GAME,
    ).games.set([games[2]])  # unfinished

    finished_game = games[0]
    PlayEvent.objects.create(game=finished_game, ended=_dt(8, 1))

    ctx = compute_stats(library, YEAR)
    return {
        "html": str(stats_content(ctx)),
        "pc": pc,
        "games": games,
        "user": library.user,
    }


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
    # the rendered link embeds the platform name as a display label (#224)
    pc = rendered["pc"]
    url = _href(stats_links.sessions_for_platform(pc.id, YEAR, pc.name))
    assert url in rendered["html"]


def test_unspecified_platform_row_links_to_null_bucket_sessions(
    db, client, django_user_model
):
    """A platformless game's playtime lands in the stats "Unspecified" platform
    row; its link must carry the IS_NULL composition and match the same
    sessions (issue #290)."""
    user = django_user_model.objects.create_user(username="u2", password="p")
    platformless_game = Game.objects.create(library=user.library, name="Homebrew")
    start = _dt(6, 1)
    Session.objects.create(
        game=platformless_game,
        timestamp_start=start,
        timestamp_end=start + timedelta(hours=1),
    )
    ctx = compute_stats(user.library, YEAR)
    html = str(stats_content(ctx))
    assert "Unspecified" in html

    link_filter = stats_links.sessions_for_platform(None, YEAR)
    assert _href(link_filter) in html

    expected = Session.objects.filter(game__platform__isnull=True).count()
    assert (
        Session.objects.filter(link_filter.to_q()).distinct().count() == expected == 1
    )

    client.force_login(user)
    response = client.get(filter_url(link_filter), follow=True)
    assert response.status_code == 200


def test_game_row_has_session_link(rendered):
    # at least one games-by-playtime game links to its sessions, with the game
    # name embedded as a display label (#224)
    any_game = rendered["games"][0]
    url = _href(stats_links.sessions_for_game(any_game.id, YEAR, any_game.name))
    assert url in rendered["html"]


def test_games_by_playtime_capped_with_view_all(rendered):
    # 6 games played, capped to 5 → a "View all" link to games_played
    assert "View all" in rendered["html"]
    view_all = filter_url(stats_links.games_played(YEAR), sort="-playtime")
    # the filter portion (before &sort) must be present even after attr-escaping
    assert escape(view_all.split("&")[0]) in rendered["html"]


def test_all_purchases_section_removed(rendered):
    assert "All Purchases" not in rendered["html"]


def test_generated_links_resolve_to_200(rendered, client):
    """A stats link, when visited, returns 200 with its filter applied."""
    client.force_login(rendered["user"])
    for builder in (
        stats_links.purchases_total(YEAR),
        stats_links.purchases_dropped(YEAR),
        stats_links.sessions_for_platform(rendered["pc"].id, YEAR),
    ):
        response = client.get(filter_url(builder), follow=True)
        assert response.status_code == 200


def test_count_links_carry_the_link_treatment(rendered):
    """The row hack that used to force underlines from the outside is gone, so
    a link that stops carrying its own would now render bare — and silently."""
    assert "text-fg-link" in rendered["html"]
    assert "underline" in rendered["html"]


def test_play_glyph_is_an_icon_link_without_an_underline(rendered):
    """Its opposite: the play glyph is deliberately unstyled as a text link, and
    no longer needs decoration-transparent to opt out of an inherited rule."""
    html = rendered["html"]
    start = html.index('title="View sessions"')
    anchor_start = html.rindex("<a", 0, start)
    anchor = html[anchor_start : html.index(">", start) + 1]
    assert "underline" not in anchor
    assert "text-fg-link" not in anchor
    assert "decoration-transparent" not in anchor
