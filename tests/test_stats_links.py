"""Parity tests for stats-page filter-link builders (issue #65).

Each builder returns a filter object; the test asserts the filter's queryset
count equals the value the stats page displays for that category, so a link can
never land on a list whose total differs from the number it was clicked from.

Data is single-game purchases (the project's modeling norm — multi-item orders
are separate single-game purchases), where the filter system's id-set semantics
match the stats queries' M2M traversal exactly.
"""

from datetime import datetime, timezone

import pytest

from games.models import Game, Platform, PlayEvent, Purchase, Session
from games.views import stats_links
from games.views.stats_data import compute_stats

YEAR = 2024


def _dt(year, month=6, day=1):
    return datetime(year, month, day, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def world(db):
    pc = Platform.objects.create(name="PC")
    switch = Platform.objects.create(name="Switch")

    finished_game = Game.objects.create(
        name="Finished", platform=pc, status=Game.Status.FINISHED, year_released=YEAR
    )
    abandoned_game = Game.objects.create(
        name="Abandoned", platform=pc, status=Game.Status.ABANDONED
    )
    playing_game = Game.objects.create(
        name="Playing", platform=switch, status=Game.Status.PLAYED
    )

    # Sessions: in-year on two platforms + one out-of-year (excluded).
    Session.objects.create(game=finished_game, timestamp_start=_dt(YEAR, 6, 1))
    Session.objects.create(game=finished_game, timestamp_start=_dt(YEAR, 7, 2))
    Session.objects.create(game=playing_game, timestamp_start=_dt(YEAR, 6, 3))
    Session.objects.create(game=finished_game, timestamp_start=_dt(YEAR - 1, 6, 1))

    # PlayEvents: finished_game ended in-year.
    PlayEvent.objects.create(game=finished_game, ended=_dt(YEAR, 8, 1))

    # Purchases (single-game).
    Purchase.objects.create(  # finished, bought in-year
        date_purchased=_dt(YEAR, 1, 5), type=Purchase.GAME
    ).games.set([finished_game])
    Purchase.objects.create(  # abandoned -> dropped
        date_purchased=_dt(YEAR, 2, 5), type=Purchase.GAME
    ).games.set([abandoned_game])
    Purchase.objects.create(  # refunded
        date_purchased=_dt(YEAR, 3, 5),
        date_refunded=_dt(YEAR, 4, 5),
        type=Purchase.GAME,
    ).games.set([playing_game])
    Purchase.objects.create(  # unfinished (playing, not refunded/finished)
        date_purchased=_dt(YEAR, 5, 5), type=Purchase.GAME
    ).games.set([playing_game])
    # backlog decrease: bought prior year, game finished, ended in-year
    Purchase.objects.create(
        date_purchased=_dt(YEAR - 1, 5, 5), type=Purchase.GAME
    ).games.set([finished_game])

    return {
        "pc": pc,
        "switch": switch,
        "finished_game": finished_game,
        "playing_game": playing_game,
    }


def _count(filter_obj, model):
    return model.objects.filter(filter_obj.to_q()).distinct().count()


# ── Per-row session links ────────────────────────────────────────────────────


def test_sessions_for_game_matches_year_scoped_sessions(world):
    game = world["finished_game"]
    expected = Session.objects.filter(
        timestamp_start__year=YEAR, game_id=game.id
    ).count()
    assert expected == 2  # guard: the out-of-year session is excluded
    assert _count(stats_links.sessions_for_game(game.id, YEAR), Session) == expected


def test_sessions_for_platform_matches_year_scoped_sessions(world):
    platform = world["pc"]
    expected = Session.objects.filter(
        timestamp_start__year=YEAR, game__platform_id=platform.id
    ).count()
    assert (
        _count(stats_links.sessions_for_platform(platform.id, YEAR), Session)
        == expected
    )


def test_sessions_in_month_matches_that_month(world):
    expected = Session.objects.filter(
        timestamp_start__year=YEAR, timestamp_start__month=6
    ).count()
    assert expected == 2
    assert _count(stats_links.sessions_in_month(YEAR, 6), Session) == expected


def test_all_sessions_matches_total_sessions(world):
    stats = compute_stats(YEAR)
    assert _count(stats_links.all_sessions(YEAR), Session) == stats["total_sessions"]


# ── Count links ──────────────────────────────────────────────────────────────


def test_games_played_matches_total_games(world):
    stats = compute_stats(YEAR)
    assert _count(stats_links.games_played(YEAR), Game) == stats["total_games"]


def test_total_purchases_matches_count(world):
    stats = compute_stats(YEAR)
    assert (
        _count(stats_links.purchases_total(YEAR), Purchase)
        == stats["all_purchased_this_year_count"]
    )


def test_refunded_purchases_matches_count(world):
    stats = compute_stats(YEAR)
    assert (
        _count(stats_links.purchases_refunded(YEAR), Purchase)
        == stats["all_purchased_refunded_this_year_count"]
    )


# ── Tier 2: finished / dropped / unfinished / backlog (uses #67) ─────────────


def test_dropped_matches_count(world):
    stats = compute_stats(YEAR)
    assert stats["dropped_count"] == 2  # guard: discriminating, non-zero
    assert (
        _count(stats_links.purchases_dropped(YEAR), Purchase) == stats["dropped_count"]
    )


def test_unfinished_matches_count(world):
    stats = compute_stats(YEAR)
    assert stats["purchased_unfinished_count"] == 1
    assert (
        _count(stats_links.purchases_unfinished(YEAR), Purchase)
        == stats["purchased_unfinished_count"]
    )


def test_finished_matches_count(world):
    stats = compute_stats(YEAR)
    assert stats["all_finished_this_year_count"] == 2
    assert (
        _count(stats_links.purchases_finished(YEAR), Purchase)
        == stats["all_finished_this_year_count"]
    )


def test_finished_released_matches_count(world):
    stats = compute_stats(YEAR)
    assert (
        _count(stats_links.purchases_finished_released(YEAR), Purchase)
        == stats["this_year_finished_this_year_count"]
    )


def test_bought_and_finished_matches_list(world):
    stats = compute_stats(YEAR)
    expected = stats["purchased_this_year_finished_this_year"].count()
    assert expected == 1
    assert _count(stats_links.purchases_bought_and_finished(YEAR), Purchase) == expected


def test_backlog_decrease_matches_count(world):
    stats = compute_stats(YEAR)
    assert stats["backlog_decrease_count"] == 1
    assert (
        _count(stats_links.purchases_backlog_decrease(YEAR), Purchase)
        == stats["backlog_decrease_count"]
    )


# ── All-time scope (no date constraint) ──────────────────────────────────────


def test_all_sessions_alltime_matches(world):
    stats = compute_stats(None)
    assert (
        _count(stats_links.all_sessions("Alltime"), Session) == stats["total_sessions"]
    )


def test_finished_alltime_matches_backlog(world):
    stats = compute_stats(None)
    # all-time backlog_decrease_count == all-time finished count
    assert (
        _count(stats_links.purchases_backlog_decrease("Alltime"), Purchase)
        == stats["backlog_decrease_count"]
    )
