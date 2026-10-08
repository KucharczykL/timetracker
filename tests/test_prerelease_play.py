"""The setting that hides prerelease play."""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from devices import create_device
from django.db.models import Q, QuerySet
from django.urls import reverse
from django.utils import timezone
from entries import prerelease_release, record_entry
from graphs import default_graph
from historical_playtime_rows import record_row
from session_rows import duration_only_row, timed_row, tracked_run

from games.bulk_reclassification import (
    conversion_scope,
    convertible_sessions,
    reviewable_sessions,
)
from games.bulk_removal import record_resolution, record_scope
from games.bulk_sessions import session_resolution, session_scope
from games.commands.playersession import CreateSession, DurationOnlyTiming
from games.commands.session_reclassification import statement_from_session
from games.events.dispatch import dispatch
from games.filters import filter_queryset_for_library
from games.models import (
    Game,
    HistoricalPlaytime,
    PlayerSession,
    Playthrough,
    PlaythroughKind,
)
from games.reads.copy_figures import copy_counts
from games.reads.days import DayInterval
from games.reads.device_departures import sessions_naming
from games.reads.game_departures import game_departures
from games.reads.historical_playtime import (
    historical_by_month,
    historical_by_platform,
    historical_total,
    historical_years,
)
from games.reads.play_figures import distinct_days, first_play, games_in_scope
from games.reads.player_sessions import (
    SessionDays,
    game_session_days,
    listed_sessions,
    shown_sessions,
)
from games.reads.playtime import (
    PlaytimeBreakdown,
    game_playtime,
    game_playtime_between,
    game_tracked_between,
    played_years,
    playtime_between_each,
    total_playtime,
)
from games.reads.prerelease_play import (
    PRERELEASE_PLAY,
    shown_play,
    shows_prerelease_play,
)
from games.reads.releases import played_releases
from games.reads.session_figures import longest_session, session_count
from games.reads.session_organization import organization_counts
from games.views.general import model_counts
from games.views.stats_data import compute_stats
from games.writes.playersession import clone_session, reclassify_session
from timetracker import settings_resolver
from timetracker.settings_commands import change_site_setting

START = datetime(2026, 1, 1, 12, tzinfo=UTC)
DAY = date(2026, 1, 1)
EARLIER = datetime(2025, 3, 1, 12, tzinfo=UTC)
HOUR = timedelta(hours=1)

pytestmark = pytest.mark.django_db


@pytest.fixture
def graph(owned_library):
    return default_graph(Game(name="Hades", library=owned_library), owned_library)


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


def a_session(run, release, *, at=START, hours=1, **columns):
    return timed_row(run, at, at + hours * HOUR, release=release, **columns)


@pytest.fixture
def world(owned_library, graph, demo):
    """Hades on both Editions; a demo-only game."""
    demo_game = default_graph(
        Game(name="Demo Quest", library=owned_library), owned_library
    )
    demo_game_demo = prerelease_release(owned_library, demo_game.release)
    record_entry(owned_library, graph.release)
    record_entry(owned_library, demo_game.release)
    run = tracked_run(owned_library, graph.game)
    demo_run = tracked_run(owned_library, demo_game.game)
    device = create_device(owned_library, "Deck")
    return {
        "game": graph.game,
        "demo_game": demo_game.game,
        "demo_release": demo_game_demo,
        "device": device,
        "full": a_session(run, graph.release, hours=2),
        "on_demo": a_session(run, demo),
        "demo_only": a_session(
            demo_run, demo_game_demo, at=EARLIER, hours=5, device=device
        ),
        "demo_year_record": record_row(
            [demo_run], duration=6 * HOUR, when="2024", release=demo_game_demo
        ),
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
    assert played_years(owned_library) == [2024, 2025, 2026]
    hide()

    assert played_years(owned_library) == [2026]


def test_historical_breakdowns_drop_hidden_records(owned_library, world, hide):
    assert historical_years(owned_library) == [2024, 2026]
    hide()

    assert historical_years(owned_library) == [2026]
    assert [row.playtime for row in historical_by_month(owned_library, year=2026)] == [
        3 * HOUR
    ]
    assert [row.playtime for row in historical_by_platform(owned_library)] == [3 * HOUR]


def test_a_run_range_hides_demo_play_but_the_seed_keeps_it(owned_library, world, hide):
    days = DayInterval(date(2025, 1, 1), DAY)
    hide()

    assert game_playtime_between(owned_library, world["demo_game"], days).tracked == (
        timedelta(0)
    )
    assert game_tracked_between(owned_library, world["demo_game"], days) == 5 * HOUR
    assert game_session_days(owned_library, world["demo_game"]) == SessionDays(
        EARLIER.date(), EARLIER.date()
    )


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

    shown = [("full",), ("full_record",), ("full", "full_record")]

    for url, kept in zip(pages, shown, strict=True):
        html = signed_in.get(url).content.decode()
        for hidden in ("on_demo", "demo_only", "demo_record"):
            assert str(world[hidden].pk) not in html, (url, hidden)
        for row in kept:
            assert str(world[row].pk) in html, (url, row)


def test_edit_pages_open_a_hidden_row(signed_in, world, hide):
    hide()

    for url in (
        reverse("games:edit_session", args=[world["on_demo"].pk]),
        reverse("games:edit_historical_playtime", args=[world["demo_record"].pk]),
    ):
        assert signed_in.get(url).status_code == 200, url


def test_the_navbar_offers_sessions_only_when_one_shows(signed_in, world, hide):
    PlayerSession.objects.exclude(pk=world["on_demo"].pk).update(
        removed_at=timezone.now()
    )
    request = signed_in.get(reverse("games:list_sessions")).wsgi_request
    assert model_counts(request)["session_count"] is True
    hide()

    assert model_counts(request)["session_count"] is False


def test_the_api_reads_every_row(signed_in, world, hide):
    """A program reads the API, not a screen."""
    hide()

    sessions = signed_in.get("/api/session/").json()
    records = signed_in.get("/api/historical-playtime/").json()
    listed = {row["id"] for row in sessions["items"]} | {
        row["id"] for row in records["items"]
    }
    every = ("full", "on_demo", "demo_only", "full_record", "demo_record")
    assert listed >= {str(world[row].pk) for row in every}
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


def test_removal_previews_count_hidden_sessions(owned_library, world, hide):
    hide()

    assert game_departures(owned_library, world["demo_game"]).sessions == 1
    assert sessions_naming(owned_library, world["device"]).count() == 1


def test_release_filter_options_keep_hidden_releases(owned_library, world, hide):
    hide()

    assert world["demo_release"] in played_releases(owned_library)


def test_the_review_and_its_act_hide_but_the_base_keeps(
    owned_library, graph, demo, run, hide
):
    full = duration_only_row(run, DAY, 9 * HOUR, release=graph.release)
    on_demo = duration_only_row(run, DAY, 9 * HOUR, release=demo)
    hide()

    assert set(reviewable_sessions(owned_library)) == {full}
    assert set(conversion_scope(owned_library, "")) == {full}
    assert set(convertible_sessions(owned_library)) == {full, on_demo}


def test_organization_counts_drop_hidden_bucket_sessions(
    owned_library, graph, demo, run, hide
):
    bucket = Playthrough.objects.create(
        pk=uuid.uuid7(),
        library=owned_library,
        player_game=run.player_game,
        kind=PlaythroughKind.IMPORTED_HISTORY,
        created_at=timezone.now(),
    )
    a_session(bucket, graph.release)
    a_session(bucket, demo)
    assert organization_counts(owned_library).bucket == 2
    hide()

    assert organization_counts(owned_library).bucket == 1


def test_the_site_default_hides_for_a_library_without_its_own(
    owned_library, django_user_model, set_user_setting
):
    other = django_user_model.objects.create_user(username="shows").library
    set_user_setting(other.user, "SHOW_PRERELEASE_PLAY", "show")
    change_site_setting("SHOW_PRERELEASE_PLAY", "hide")
    settings_resolver.clear_cache()

    assert shows_prerelease_play(owned_library) is False
    assert shows_prerelease_play(other) is True


# ── Every figure ─────────────────────────────────────────────────────────────


def _settled(stats):
    """Querysets compare by identity; read them."""
    return {
        key: list(value) if isinstance(value, QuerySet) else value
        for key, value in stats.items()
    }


@pytest.mark.parametrize("year", [None, 2025, 2026])
def test_hiding_is_removing_the_hidden_rows_for_every_figure(
    owned_library, world, hide, set_user_setting, year
):
    hide()
    hidden = _settled(compute_stats(owned_library, year))

    set_user_setting(owned_library.user, "SHOW_PRERELEASE_PLAY", "show")
    now = timezone.now()
    PlayerSession.objects.filter(PRERELEASE_PLAY).update(removed_at=now)
    HistoricalPlaytime.objects.filter(PRERELEASE_PLAY).update(removed_at=now)
    removed = _settled(compute_stats(owned_library, year))

    assert hidden == removed


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
            implies_played=False,
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


@pytest.mark.django_db(transaction=True)
def test_resume_reads_hidden_prerelease_play(
    owned_user, owned_library, demo, run, hide
):
    device = create_device(owned_library, "Deck")
    a_session(run, demo, device=device)
    hide()

    resumed = clone_session(
        owned_user, run.player_game.game, correlation_id=uuid.uuid7()
    )

    assert resumed.device.device == device
