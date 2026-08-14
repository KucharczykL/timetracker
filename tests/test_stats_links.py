"""Parity tests for stats-page filter-link builders (issue #65).

Each builder returns a filter object; the test asserts the filter's queryset
count equals the value the stats page displays for that category, so a link can
never land on a list whose total differs from the number it was clicked from.

Data is single-game purchases (the project's modeling norm — multi-item orders
are separate single-game purchases), where the filter system's id-set semantics
match the stats queries' M2M traversal exactly.
"""

import json
from datetime import UTC, datetime

import pytest
from django.contrib.auth import get_user_model

from common.filter_execution import execute_filter
from games.filters import filter_query_context_for_library
from games.models import Game, Platform, PlayEvent, Purchase, Session
from games.views import stats_links
from games.views.stats_data import compute_stats

YEAR = 2024


def _dt(year, month=6, day=1):
    return datetime(year, month, day, 12, 0, tzinfo=UTC)


@pytest.fixture
def world(db):
    library = get_user_model().objects.create_user(username="stats-links").library
    pc = Platform.objects.create(name="PC")
    switch = Platform.objects.create(name="Switch")

    finished_game = Game.objects.create(
        library=library,
        name="Finished",
        platform=pc,
        status=Game.Status.FINISHED,
        year_released=YEAR,
    )
    abandoned_game = Game.objects.create(
        library=library, name="Abandoned", platform=pc, status=Game.Status.ABANDONED
    )
    playing_game = Game.objects.create(
        library=library, name="Playing", platform=switch, status=Game.Status.PLAYED
    )

    # Sessions: in-year on two platforms + one out-of-year (excluded).
    Session.objects.create(game=finished_game, timestamp_start=_dt(YEAR, 6, 1))
    Session.objects.create(game=finished_game, timestamp_start=_dt(YEAR, 7, 2))
    Session.objects.create(game=playing_game, timestamp_start=_dt(YEAR, 6, 3))
    Session.objects.create(game=finished_game, timestamp_start=_dt(YEAR - 1, 6, 1))

    # PlayEvents: finished_game ended in-year.
    PlayEvent.objects.create(game=finished_game, ended=_dt(YEAR, 8, 1))

    # Purchases (single-game).
    Purchase.objects.create(
        library=library,
        price_currency="CZK",  # finished, bought in-year
        date_purchased=_dt(YEAR, 1, 5),
        type=Purchase.GAME,
    ).games.set([finished_game])
    Purchase.objects.create(
        library=library,
        price_currency="CZK",  # abandoned -> dropped
        date_purchased=_dt(YEAR, 2, 5),
        type=Purchase.GAME,
    ).games.set([abandoned_game])
    Purchase.objects.create(
        library=library,
        price_currency="CZK",  # refunded
        date_purchased=_dt(YEAR, 3, 5),
        date_refunded=_dt(YEAR, 4, 5),
        type=Purchase.GAME,
    ).games.set([playing_game])
    Purchase.objects.create(
        library=library,
        price_currency="CZK",  # unfinished (playing, not refunded/finished)
        date_purchased=_dt(YEAR, 5, 5),
        type=Purchase.GAME,
    ).games.set([playing_game])
    # backlog decrease: bought prior year, game finished, ended in-year
    Purchase.objects.create(
        library=library,
        price_currency="CZK",
        date_purchased=_dt(YEAR - 1, 5, 5),
        type=Purchase.GAME,
    ).games.set([finished_game])

    foreign_library = (
        get_user_model().objects.create_user(username="stats-links-foreign").library
    )
    foreign_game = Game.objects.create(
        library=foreign_library,
        name="Foreign Finished",
        platform=pc,
        status=Game.Status.FINISHED,
        year_released=YEAR,
    )
    Session.objects.create(
        game=foreign_game,
        timestamp_start=_dt(YEAR, 6, 4),
    )
    Purchase.objects.create(
        library=foreign_library,
        price_currency="CZK",
        date_purchased=_dt(YEAR, 1, 6),
        type=Purchase.GAME,
    ).games.set([foreign_game])

    return {
        "library": library,
        "foreign_library": foreign_library,
        "pc": pc,
        "switch": switch,
        "finished_game": finished_game,
        "playing_game": playing_game,
    }


def _stats(world, year):
    return compute_stats(world["library"], year)


def _count(filter_obj, model, library):
    queryset = model.objects.for_library(library)
    return (
        execute_filter(filter_obj, queryset, filter_query_context_for_library(library))
        .distinct()
        .count()
    )


def _count_via_json(filter_obj, model, library):
    """Count after a full JSON round-trip, mirroring what a clicked stats link
    does: serialize to the ``?filter=`` payload and deserialize in the view.

    On the pre-fix serializer this drops cross-entity sub-filters (issue #120),
    so the count diverges from the in-memory ``_count`` for nested builders.
    """
    restored = type(filter_obj).from_json(json.loads(json.dumps(filter_obj.to_json())))
    return _count(restored, model, library)


# ── Per-row session links ────────────────────────────────────────────────────


def test_sessions_for_game_matches_year_scoped_sessions(world):
    game = world["finished_game"]
    expected = (
        Session.objects.for_library(world["library"])
        .filter(timestamp_start__year=YEAR, game_id=game.id)
        .count()
    )
    assert expected == 2  # guard: the out-of-year session is excluded
    assert (
        _count(stats_links.sessions_for_game(game.id, YEAR), Session, world["library"])
        == expected
    )


def test_sessions_for_platform_matches_year_scoped_sessions(world):
    platform = world["pc"]
    expected = (
        Session.objects.for_library(world["library"])
        .filter(timestamp_start__year=YEAR, game__platform_id=platform.id)
        .count()
    )
    assert (
        _count(
            stats_links.sessions_for_platform(platform.id, YEAR),
            Session,
            world["library"],
        )
        == expected
    )


def test_sessions_for_platform_null_bucket_matches_stats_grouping(world):
    """The stats "Unspecified" bucket groups by the game__platform LEFT JOIN, so
    it holds sessions of platformless games. The None link must match that set."""
    platformless_game = Game.objects.create(library=world["library"], name="Homebrew")
    Session.objects.create(game=platformless_game, timestamp_start=_dt(YEAR, 6, 5))
    Session.objects.create(game=platformless_game, timestamp_start=_dt(YEAR - 1, 6, 5))

    expected = (
        Session.objects.for_library(world["library"])
        .filter(timestamp_start__year=YEAR, game__platform__isnull=True)
        .count()
    )
    assert expected == 1  # guard: the out-of-year session is excluded
    assert (
        _count(stats_links.sessions_for_platform(None, YEAR), Session, world["library"])
        == expected
    )


def test_sessions_for_platform_null_bucket_survives_json_round_trip(world):
    platformless_game = Game.objects.create(library=world["library"], name="Homebrew")
    Session.objects.create(game=platformless_game, timestamp_start=_dt(YEAR, 6, 5))

    link_filter = stats_links.sessions_for_platform(None, YEAR)
    assert _count_via_json(link_filter, Session, world["library"]) == _count(
        link_filter, Session, world["library"]
    )


def test_sessions_for_game_embeds_label(world):
    """A game session-link carries the game name as a display label so the
    destination filter bar renders a named pill, not a bare id (#224)."""
    game = world["finished_game"]
    payload = stats_links.sessions_for_game(game.id, YEAR, game.name).to_json()
    assert payload["game"]["value"] == [{"id": game.id, "label": game.name}]


def test_sessions_for_platform_embeds_label(world):
    """The platform name rides into the nested game_filter.platform criterion so
    the session bar's cross-entity platform pill renders a name (#224)."""
    platform = world["pc"]
    payload = stats_links.sessions_for_platform(
        platform.id, YEAR, platform.name
    ).to_json()
    assert payload["game_filter"]["platform"]["value"] == [
        {"id": platform.id, "label": platform.name}
    ]


def test_sessions_for_game_without_label_stays_bare(world):
    """No label given -> serialization is unchanged (bare id)."""
    game = world["finished_game"]
    payload = stats_links.sessions_for_game(game.id, YEAR).to_json()
    assert payload["game"]["value"] == [game.id]


def test_games_in_month_matches_that_month(world):
    expected = (
        Game.objects.for_library(world["library"])
        .filter(
            sessions__in=Session.objects.for_library(world["library"]).filter(
                timestamp_start__year=YEAR, timestamp_start__month=6
            )
        )
        .count()
    )
    assert expected == 2
    assert (
        _count(stats_links.games_in_month(YEAR, 6), Game, world["library"]) == expected
    )


def test_all_sessions_matches_total_sessions(world):
    stats = _stats(world, YEAR)
    assert (
        _count(stats_links.all_sessions(YEAR), Session, world["library"])
        == stats["total_sessions"]
    )


# ── Count links ──────────────────────────────────────────────────────────────


def test_games_played_matches_total_games(world):
    stats = _stats(world, YEAR)
    assert (
        _count(stats_links.games_played(YEAR), Game, world["library"])
        == stats["total_games"]
    )


def test_total_purchases_matches_count(world):
    stats = _stats(world, YEAR)
    assert (
        _count(stats_links.purchases_total(YEAR), Purchase, world["library"])
        == stats["all_purchased_this_year_count"]
    )


def test_refunded_purchases_matches_count(world):
    stats = _stats(world, YEAR)
    assert (
        _count(stats_links.purchases_refunded(YEAR), Purchase, world["library"])
        == stats["all_purchased_refunded_this_year_count"]
    )


# ── Tier 2: finished / dropped / unfinished / backlog (uses #67) ─────────────


def test_dropped_matches_count(world):
    stats = _stats(world, YEAR)
    assert stats["dropped_count"] == 2  # guard: discriminating, non-zero
    assert (
        _count(stats_links.purchases_dropped(YEAR), Purchase, world["library"])
        == stats["dropped_count"]
    )


def test_unfinished_matches_count(world):
    stats = _stats(world, YEAR)
    assert stats["purchased_unfinished_count"] == 1
    assert (
        _count(stats_links.purchases_unfinished(YEAR), Purchase, world["library"])
        == stats["purchased_unfinished_count"]
    )


def test_finished_matches_count(world):
    stats = _stats(world, YEAR)
    assert stats["all_finished_this_year_count"] == 2
    assert (
        _count(stats_links.purchases_finished(YEAR), Purchase, world["library"])
        == stats["all_finished_this_year_count"]
    )


def test_finished_released_matches_count(world):
    stats = _stats(world, YEAR)
    assert (
        _count(
            stats_links.purchases_finished_released(YEAR), Purchase, world["library"]
        )
        == stats["this_year_finished_this_year_count"]
    )


def test_bought_and_finished_matches_list(world):
    stats = _stats(world, YEAR)
    expected = stats["purchased_this_year_finished_this_year"].count()
    assert expected == 1
    assert (
        _count(
            stats_links.purchases_bought_and_finished(YEAR), Purchase, world["library"]
        )
        == expected
    )


def test_backlog_decrease_matches_count(world):
    stats = _stats(world, YEAR)
    assert stats["backlog_decrease_count"] == 1
    assert (
        _count(stats_links.purchases_backlog_decrease(YEAR), Purchase, world["library"])
        == stats["backlog_decrease_count"]
    )


# ── All-time scope (no date constraint) ──────────────────────────────────────


def test_all_sessions_alltime_matches(world):
    stats = _stats(world, None)
    assert (
        _count(stats_links.all_sessions("Alltime"), Session, world["library"])
        == stats["total_sessions"]
    )


def test_finished_alltime_matches_backlog(world):
    stats = _stats(world, None)
    # all-time backlog_decrease_count == all-time finished count
    assert (
        _count(
            stats_links.purchases_backlog_decrease("Alltime"),
            Purchase,
            world["library"],
        )
        == stats["backlog_decrease_count"]
    )


# ── JSON round-trip parity (issue #120) ──────────────────────────────────────
#
# Builders that nest cross-entity sub-filters (game_filter / session_filter /
# playevent_filter). Before the serialization fix these serialized to an empty
# or partial `?filter=`, so a clicked link landed on an unfiltered list. Each


def test_stats_link_destination_count_parity_for_each_library(world):
    link_filter = stats_links.all_sessions(YEAR)
    own_count = _count(link_filter, Session, world["library"])
    foreign_count = _count(link_filter, Session, world["foreign_library"])

    assert own_count == compute_stats(world["library"], YEAR)["total_sessions"]
    assert (
        foreign_count == compute_stats(world["foreign_library"], YEAR)["total_sessions"]
    )
    assert (own_count, foreign_count) == (3, 1)


# must survive the same to_json → from_json the view performs.

_NESTED_BUILDERS = [
    ("purchases_finished", lambda: stats_links.purchases_finished(YEAR), Purchase),
    (
        "purchases_finished_released",
        lambda: stats_links.purchases_finished_released(YEAR),
        Purchase,
    ),
    (
        "purchases_bought_and_finished",
        lambda: stats_links.purchases_bought_and_finished(YEAR),
        Purchase,
    ),
    ("purchases_dropped", lambda: stats_links.purchases_dropped(YEAR), Purchase),
    ("purchases_unfinished", lambda: stats_links.purchases_unfinished(YEAR), Purchase),
    (
        "purchases_backlog_decrease",
        lambda: stats_links.purchases_backlog_decrease(YEAR),
        Purchase,
    ),
    ("games_played", lambda: stats_links.games_played(YEAR), Game),
    (
        "sessions_for_platform",
        lambda: stats_links.sessions_for_platform(1, YEAR),
        Session,
    ),
]


@pytest.mark.parametrize("name,builder,model", _NESTED_BUILDERS)
def test_nested_builder_survives_json_round_trip(world, name, builder, model):
    filter_obj = builder()
    # Sanity check: the builder serialized to a non-empty payload (Session
    # builders are exempt — sessions_for_platform may serialize flat-only).
    serialized = filter_obj.to_json()
    assert serialized != {} or model is Session, f"{name}: nothing serialized"
    assert _count_via_json(filter_obj, model, world["library"]) == _count(
        filter_obj, model, world["library"]
    ), f"{name}: JSON round-trip changed the result set"


def test_finished_link_round_trips_to_same_count_as_stat(world):
    stats = _stats(world, YEAR)
    assert (
        _count_via_json(
            stats_links.purchases_finished(YEAR), Purchase, world["library"]
        )
        == stats["all_finished_this_year_count"]
    )
