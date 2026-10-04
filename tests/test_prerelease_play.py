"""The setting that hides prerelease play."""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from django.db.models import Q
from django.urls import reverse
from entries import prerelease_release, record_entry
from historical_playtime_rows import record_row
from session_rows import timed_row, tracked_run

from games.bulk_removal import record_resolution, record_scope
from games.bulk_sessions import session_resolution, session_scope
from games.commands.playersession import CreateSession, DurationOnlyTiming
from games.commands.session_reclassification import statement_from_session
from games.events.dispatch import dispatch
from games.filters import filter_queryset_for_library
from games.models import Game, HistoricalPlaytime, PlayerSession
from games.reads.copy_figures import copy_counts
from games.reads.days import DayInterval
from games.reads.historical_playtime import historical_total
from games.reads.play_figures import distinct_days, first_play, games_in_scope
from games.reads.player_sessions import listed_sessions, shown_sessions
from games.reads.playtime import (
    PlaytimeBreakdown,
    game_playtime,
    game_tracked_between,
    played_years,
    playtime_between_each,
    total_playtime,
)
from games.reads.prerelease_play import shown_play, shows_prerelease_play
from games.reads.session_figures import longest_session, session_count
from games.writes.playersession import reclassify_session

START = datetime(2026, 1, 1, 12, tzinfo=UTC)
DAY = date(2026, 1, 1)
EARLIER = datetime(2025, 3, 1, 12, tzinfo=UTC)
HOUR = timedelta(hours=1)

pytestmark = pytest.mark.django_db


@pytest.fixture
def graph(owned_library, stated_graph):
    return stated_graph(Game(name="Hades", library=owned_library), owned_library)


@pytest.fixture
def demo(owned_library, graph):
    return prerelease_release(owned_library, graph.release)


@pytest.fixture
def run(owned_library, graph):
    return tracked_run(owned_library, graph.game)


@pytest.fixture
def hide(owned_library, set_user_setting):
    def hidden():
        set_user_setting(owned_library.user, "SHOW_PRERELEASE_PLAY", "hide")

    return hidden


def a_session(run, release, *, at=START, hours=1):
    return timed_row(run, at, at + hours * HOUR, release=release)


@pytest.fixture
def world(owned_library, graph, demo, stated_graph):
    """Hades on both Editions; a game played only on its demo, earlier."""
    demo_game = stated_graph(
        Game(name="Demo Quest", library=owned_library), owned_library
    )
    demo_game_demo = prerelease_release(owned_library, demo_game.release)
    record_entry(owned_library, graph.release)
    record_entry(owned_library, demo_game.release)
    run = tracked_run(owned_library, graph.game)
    demo_run = tracked_run(owned_library, demo_game.game)
    return {
        "game": graph.game,
        "demo_game": demo_game.game,
        "full": a_session(run, graph.release, hours=2),
        "on_demo": a_session(run, demo),
        "demo_only": a_session(demo_run, demo_game_demo, at=EARLIER, hours=5),
        "full_record": record_row(
            [run], duration=3 * HOUR, when="2026-01-01", release=graph.release
        ),
        "demo_record": record_row(
            [run], duration=4 * HOUR, when="2026-01-01", release=demo
        ),
    }


# ── The reader ───────────────────────────────────────────────────────────────


def test_prerelease_play_shows_by_default(owned_library):
    assert shows_prerelease_play(owned_library) is True
    assert shown_play(owned_library) == Q()


def test_hidden_prerelease_play_drops_only_demo_sessions(
    owned_library, graph, demo, run, hide
):
    unnamed = a_session(run, None)
    full = a_session(run, graph.release)
    a_session(run, demo)
    hide()

    assert shows_prerelease_play(owned_library) is False
    shown = set(PlayerSession.objects.filter(shown_play(owned_library)))
    assert shown == {unnamed, full}


def test_hidden_prerelease_play_drops_only_demo_records(
    owned_library, graph, demo, run, hide
):
    unnamed = record_row([run])
    full = record_row([run], release=graph.release)
    record_row([run], release=demo)
    hide()

    shown = set(HistoricalPlaytime.objects.filter(shown_play(owned_library)))
    assert shown == {unnamed, full}


def test_shown_prerelease_play_keeps_every_row(owned_library, graph, demo, run):
    rows = {a_session(run, None), a_session(run, graph.release), a_session(run, demo)}

    assert set(PlayerSession.objects.filter(shown_play(owned_library))) == rows


# ── Figures ──────────────────────────────────────────────────────────────────


def test_playtime_figures_drop_hidden_play(owned_library, world, hide):
    assert game_playtime(owned_library, world["game"]) == PlaytimeBreakdown(
        3 * HOUR, 7 * HOUR
    )
    hide()

    assert game_playtime(owned_library, world["game"]) == PlaytimeBreakdown(
        2 * HOUR, 3 * HOUR
    )
    assert total_playtime(owned_library) == PlaytimeBreakdown(2 * HOUR, 3 * HOUR)
    assert historical_total(owned_library) == 3 * HOUR
    #: The navbar's windows.
    assert playtime_between_each(owned_library, [DayInterval(DAY, DAY)]) == [
        PlaytimeBreakdown(2 * HOUR, 3 * HOUR)
    ]


def test_played_years_drop_a_year_only_demo_play_reaches(owned_library, world, hide):
    assert played_years(owned_library) == [2025, 2026]
    hide()

    assert played_years(owned_library) == [2026]


def test_session_and_day_figures_drop_hidden_play(owned_library, world, hide):
    assert session_count(owned_library, None) == 3
    assert distinct_days(owned_library, None) == 2
    hide()

    assert session_count(owned_library, None) == 1
    assert longest_session(owned_library, None).session == world["full"]
    assert distinct_days(owned_library, None) == 1
    assert first_play(owned_library, None).game == world["game"]
    assert set(games_in_scope(owned_library, None)) == {world["game"]}


def test_games_played_drops_a_demo_only_game_and_backlog_stays(
    owned_library, world, hide
):
    shown = copy_counts(owned_library, None)
    hide()
    hidden = copy_counts(owned_library, None)

    assert (shown.played, hidden.played) == (2, 1)
    assert hidden._replace(played=0) == shown._replace(played=0)


# ── Lists ────────────────────────────────────────────────────────────────────


def test_list_scope_is_the_filter_scope(owned_library, world, hide):
    hide()

    assert set(listed_sessions(owned_library)) == {world["full"]}
    assert set(filter_queryset_for_library("playersession", owned_library)) == {
        world["full"]
    }
    assert set(filter_queryset_for_library("historicalplaytime", owned_library)) == {
        world["full_record"]
    }


@pytest.fixture
def signed_in(client, owned_user):
    client.force_login(owned_user)
    return client


def test_pages_drop_hidden_rows(signed_in, world, hide):
    hide()
    game = world["game"]
    pages = [
        reverse("games:list_sessions"),
        reverse("games:list_historical_playtime"),
        reverse("games:view_game", args=[game.pk, game.url_slug]),
    ]

    for url in pages:
        html = signed_in.get(url).content.decode()
        for hidden in ("on_demo", "demo_only", "demo_record"):
            assert str(world[hidden].pk) not in html, (url, hidden)
    game_page = signed_in.get(pages[2]).content.decode()
    assert str(world["full"].pk) in game_page
    assert str(world["full_record"].pk) in game_page


def test_api_lists_hide_but_one_row_reads_find(signed_in, world, hide):
    hide()

    sessions = signed_in.get("/api/session/").json()
    records = signed_in.get("/api/historical-playtime/").json()
    listed = {row["id"] for row in sessions["items"]} | {
        row["id"] for row in records["items"]
    }
    assert listed == {str(world["full"].pk), str(world["full_record"].pk)}
    for path in (
        f"/api/session/{world['on_demo'].pk}",
        f"/api/historical-playtime/{world['demo_record'].pk}",
    ):
        assert signed_in.get(path).status_code == 200, path


# ── Acts ─────────────────────────────────────────────────────────────────────


def test_bulk_scopes_hide_but_resolutions_find(owned_library, world, hide):
    hide()

    assert set(session_scope(owned_library, "")) == {world["full"]}
    assert set(record_scope(owned_library, "")) == {world["full_record"]}
    found = session_resolution(owned_library, [world["on_demo"].pk])
    assert [row.pk for row in found.rows] == [world["on_demo"].pk]
    found = record_resolution(owned_library, [world["demo_record"].pk])
    assert [row.pk for row in found.rows] == [world["demo_record"].pk]


def test_the_seed_reads_every_session(owned_library, world, hide):
    hide()

    assert (
        game_tracked_between(
            owned_library, world["demo_game"], DayInterval(date(2025, 1, 1), DAY)
        )
        == 5 * HOUR
    )


@pytest.mark.django_db(transaction=True)
def test_a_reclassified_hidden_session_stays_hidden(owned_library, graph, demo, hide):
    record_entry(owned_library, graph.release)
    record_entry(owned_library, demo)
    run = tracked_run(owned_library, graph.game)
    dispatch(
        CreateSession(
            playthrough_id=run.pk,
            timing=DurationOnlyTiming(day=DAY, duration=10 * HOUR),
            release_id=demo.pk,
        ),
        actor=owned_library.user,
        library=owned_library,
        idempotency_key=str(uuid.uuid7()),
    )
    session = PlayerSession.objects.get()
    hide()
    assert total_playtime(owned_library) == PlaytimeBreakdown(
        timedelta(0), timedelta(0)
    )

    reclassify_session(
        owned_library.user,
        session,
        statement_from_session(session),
        idempotency_key=str(uuid.uuid7()),
        correlation_id=uuid.uuid7(),
    )

    assert not shown_sessions(owned_library).exists()
    assert total_playtime(owned_library) == PlaytimeBreakdown(
        timedelta(0), timedelta(0)
    )
    assert HistoricalPlaytime.objects.get().release == demo
