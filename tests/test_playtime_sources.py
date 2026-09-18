"""Playtime read from the session projection."""

from datetime import UTC, date, datetime, time, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone
from historical_playtime_rows import record_row
from session_rows import (
    TWIN_ZONE,
    corrected_row,
    duration_only_row,
    timed_row,
    tracked_run,
)

from common.filter_execution import execute_filter
from games.filters import (
    GameFilter,
    PlayerSessionFilter,
    filter_query_context_for_library,
)
from games.models import Device, Game, Platform, UserLibrary
from games.reads.days import DayInterval
from games.reads.historical_playtime import PlatformHistorical
from games.reads.playtime import (
    MonthPlaytime,
    PlatformPlaytime,
    PlaytimeBreakdown,
    UnscopedPlaytimeRead,
    _merged,
    game_playtime,
    game_playtime_between,
    game_tracked_between,
    played_years,
    playtime_between,
    playtime_between_each,
    playtime_by_game,
    playtime_by_month,
    playtime_by_platform,
    playtime_matching,
    playtime_sort_key,
    total_playtime,
    tracked_summed_by_game,
    tracked_summed_by_game_matching,
)
from games.reads.unscoped import UnscopedRead

ZERO = timedelta(0)


def tracked(playtime: timedelta) -> PlaytimeBreakdown:
    return PlaytimeBreakdown(tracked=playtime, historical=ZERO)


@pytest.fixture
def platform() -> Platform:
    return Platform.objects.create(name="PC", icon="pc")


@pytest.fixture
def game(owned_library, platform) -> Game:
    return Game.objects.create(
        library=owned_library, name="Outer Wilds", platform=platform
    )


@pytest.fixture
def stranger_library(django_user_model) -> UserLibrary:
    return django_user_model.objects.create_user(
        username="stranger", password="p"
    ).library


def summed(library: UserLibrary | None, game: Game, **scope):
    """The sum on one game."""
    return (
        Game.objects.filter(pk=game.pk)
        .annotate(figure=tracked_summed_by_game(library, **scope))
        .get()
        .figure
    )


def prague(hour: int, day: date) -> datetime:
    return datetime.combine(day, time(hour), tzinfo=TWIN_ZONE)


def timed(library: UserLibrary, game: Game, started_at, ended_at):
    return timed_row(
        tracked_run(library, game), started_at, ended_at, day_zone=TWIN_ZONE.key
    )


@pytest.mark.django_db
def test_every_scalar_figure_is_zero_for_an_empty_library(owned_library, game):
    days = DayInterval(date(2026, 1, 1), date(2026, 12, 31))
    assert game_playtime(owned_library, game).total == ZERO
    assert game_playtime_between(owned_library, game, days).total == ZERO
    assert total_playtime(owned_library).total == ZERO
    assert total_playtime(owned_library, year=2026).total == ZERO
    assert playtime_between(owned_library, days).total == ZERO
    assert playtime_by_platform(owned_library) == []
    assert playtime_by_month(owned_library, year=2026) == []
    assert played_years(owned_library) == []


@pytest.mark.django_db
def test_an_unplayed_game_sums_to_null(owned_library, game):
    assert summed(owned_library, game) is None


@pytest.mark.django_db
def test_the_sum_is_null_for_an_unplayed_game(owned_library, game):
    figures = (
        Game.objects.tracked_by(owned_library)
        .annotate(
            sort_key=playtime_sort_key(owned_library),
            by_game=playtime_by_game(owned_library),
        )
        .get()
    )

    assert figures.sort_key is None
    assert figures.by_game == ZERO


@pytest.mark.django_db
def test_a_row_of_each_mode_counts_its_effective_duration(
    owned_library, game, platform
):
    day = date(2026, 3, 5)
    run = tracked_run(owned_library, game)
    timed(owned_library, game, prague(10, day), prague(12, day))
    duration_only_row(run, date(2026, 4, 2), timedelta(minutes=90))
    corrected_row(
        run,
        prague(20, day),
        prague(21, day),
        timedelta(minutes=30),
        day_zone=TWIN_ZONE.key,
    )
    total = timedelta(hours=4)

    with timezone.override(TWIN_ZONE):
        figures = {
            "game": game_playtime(owned_library, game).total,
            "summed": summed(owned_library, game),
            "summed in year": summed(owned_library, game, year=2026),
            "total": total_playtime(owned_library).total,
            "total in year": total_playtime(owned_library, year=2026).total,
            "between": playtime_between(owned_library, DayInterval.single(day)).total,
            "game between": game_playtime_between(
                owned_library, game, DayInterval.single(day)
            ).total,
            "platforms": playtime_by_platform(owned_library),
            "platforms in year": playtime_by_platform(owned_library, year=2026),
            "months": playtime_by_month(owned_library, year=2026),
            "years": played_years(owned_library),
        }

    #: Corrected: stated time replaces elapsed.
    assert figures == {
        "game": total,
        "summed": total,
        "summed in year": total,
        "total": total,
        "total in year": total,
        "between": timedelta(hours=2, minutes=30),
        "game between": timedelta(hours=2, minutes=30),
        "platforms": [PlatformPlaytime(platform.pk, "PC", tracked(total))],
        "platforms in year": [PlatformPlaytime(platform.pk, "PC", tracked(total))],
        "months": [
            MonthPlaytime(date(2026, 3, 1), tracked(timedelta(hours=2, minutes=30))),
            MonthPlaytime(date(2026, 4, 1), tracked(timedelta(minutes=90))),
        ],
        "years": [2026],
    }


@pytest.mark.django_db
def test_a_running_timed_row_counts_zero(owned_library, game):
    started_at = prague(10, date(2026, 3, 5))
    timed(owned_library, game, started_at, None)

    with timezone.override(TWIN_ZONE):
        assert game_playtime(owned_library, game).total == ZERO
        assert (
            game_playtime_between(
                owned_library, game, DayInterval.single(started_at.date())
            ).total
            == ZERO
        )
        assert total_playtime(owned_library).total == ZERO
        assert total_playtime(owned_library, year=2026).total == ZERO


@pytest.mark.django_db
def test_the_stored_day_is_read_whatever_the_active_zone(owned_library, game):
    started_at = datetime(2025, 12, 31, 23, 30, tzinfo=UTC)
    timed_row(
        tracked_run(owned_library, game),
        started_at,
        started_at + timedelta(minutes=20),
        day_zone="Europe/Prague",
    )

    for zone in (TWIN_ZONE, ZoneInfo("UTC")):
        with timezone.override(zone):
            assert total_playtime(owned_library, year=2026).total == timedelta(
                minutes=20
            )
            assert total_playtime(owned_library, year=2025).total == ZERO
            assert played_years(owned_library) == [2026]


@pytest.mark.django_db
def test_a_duration_only_row_lands_on_its_written_day(owned_library, game):
    day = date(2026, 3, 5)
    duration = timedelta(minutes=90)
    duration_only_row(tracked_run(owned_library, game), day, duration)

    with timezone.override(TWIN_ZONE):
        assert total_playtime(owned_library, year=2026).total == duration
        assert playtime_by_month(owned_library, year=2026) == [
            MonthPlaytime(date(2026, 3, 1), tracked(duration))
        ]
        assert (
            playtime_between(owned_library, DayInterval.single(day)).total == duration
        )
        assert (
            playtime_between(
                owned_library, DayInterval.single(day + timedelta(days=1))
            ).total
            == ZERO
        )


@pytest.mark.django_db
def test_a_day_window_is_inclusive(owned_library, game):
    first, last = date(2026, 3, 5), date(2026, 3, 7)
    inside = timedelta(minutes=10)
    outside = timedelta(minutes=1)
    before_first = datetime.combine(first, time(0), tzinfo=TWIN_ZONE)
    timed(owned_library, game, before_first, before_first + inside)
    late_on_last = datetime.combine(last, time(23, 30), tzinfo=TWIN_ZONE)
    timed(owned_library, game, late_on_last, late_on_last + inside)
    timed(
        owned_library,
        game,
        before_first - timedelta(minutes=5),
        before_first - timedelta(minutes=4),
    )
    after_last = datetime.combine(last + timedelta(days=1), time(0), tzinfo=TWIN_ZONE)
    timed(owned_library, game, after_last, after_last + outside)

    with timezone.override(TWIN_ZONE):
        assert (
            playtime_between(owned_library, DayInterval(first, last)).total
            == 2 * inside
        )


@pytest.mark.django_db
def test_a_games_window_counts_that_game_alone(owned_library, game):
    """One game, inclusive days, in the library's calendar."""
    first, last = date(2026, 3, 5), date(2026, 3, 7)
    inside = timedelta(minutes=10)
    other = Game.objects.create(library=owned_library, name="Tunic")
    run = tracked_run(owned_library, game)
    on_first = datetime.combine(first, time(0), tzinfo=TWIN_ZONE)
    timed(owned_library, game, on_first, on_first + inside)
    late_on_last = datetime.combine(last, time(23, 30), tzinfo=TWIN_ZONE)
    timed(owned_library, game, late_on_last, late_on_last + inside)
    duration_only_row(run, last, inside)
    corrected_row(run, on_first, on_first + inside, inside, day_zone=TWIN_ZONE.key)
    timed(owned_library, other, on_first, on_first + inside)
    before = on_first - timedelta(minutes=5)
    timed(owned_library, game, before, before + inside)
    after = datetime.combine(last + timedelta(days=1), time(0), tzinfo=TWIN_ZONE)
    timed(owned_library, game, after, after + inside)

    with timezone.override(TWIN_ZONE):
        figure = game_playtime_between(
            owned_library, game, DayInterval(first, last)
        ).total

    assert figure == 4 * inside


@pytest.mark.django_db
def test_a_games_window_never_counts_another_library(owned_library, stranger_library):
    shared = Game.objects.create(library=None, name="Tetris")
    started_at = datetime(2026, 3, 5, 10, tzinfo=UTC)
    days = DayInterval.single(started_at.date())
    for library, hours in ((owned_library, 1), (stranger_library, 2)):
        ended_at = started_at + timedelta(hours=hours)
        timed_row(tracked_run(library, shared), started_at, ended_at)

    assert game_playtime_between(owned_library, shared, days).total == timedelta(
        hours=1
    )
    assert game_playtime_between(stranger_library, shared, days).total == timedelta(
        hours=2
    )


@pytest.mark.django_db
def test_summed_by_game_never_counts_another_library(owned_library, stranger_library):
    shared = Game.objects.create(library=None, name="Tetris")
    started_at = datetime(2026, 3, 5, 10, tzinfo=UTC)
    for library, hours in ((owned_library, 1), (stranger_library, 2)):
        ended_at = started_at + timedelta(hours=hours)
        timed_row(tracked_run(library, shared), started_at, ended_at)

    assert (summed(owned_library, shared), summed(stranger_library, shared)) == (
        timedelta(hours=1),
        timedelta(hours=2),
    )


@pytest.mark.django_db
def test_a_session_filter_narrows_the_sum(owned_library, game):
    handheld = Device.objects.create(library=owned_library, name="Deck")
    desktop = Device.objects.create(library=owned_library, name="Tower")
    started_at = datetime(2026, 3, 5, 10, tzinfo=UTC)
    for device, hours in ((handheld, 1), (desktop, 2)):
        timed_row(
            tracked_run(owned_library, game),
            started_at,
            started_at + timedelta(hours=hours),
            device=device,
        )
    on_the_handheld = PlayerSessionFilter.where(device=[handheld.pk])

    figures = (
        Game.objects.filter(pk=game.pk)
        .annotate(
            matching=tracked_summed_by_game_matching(owned_library, on_the_handheld),
            filtered=playtime_matching(owned_library, on_the_handheld),
            unfiltered=playtime_sort_key(owned_library),
        )
        .get()
    )

    assert figures.matching == timedelta(hours=1)
    assert figures.filtered == timedelta(hours=1)
    assert figures.unfiltered == total_playtime(owned_library).total
    assert figures.unfiltered == timedelta(hours=3)


@pytest.mark.django_db
def test_summed_by_game_over_no_library_refuses_to_execute(stranger_library):
    shared = Game.objects.create(library=None, name="Tetris")
    started_at = datetime(2026, 3, 5, 10, tzinfo=UTC)
    timed_row(
        tracked_run(stranger_library, shared),
        started_at,
        started_at + timedelta(hours=1),
    )

    with pytest.raises(UnscopedPlaytimeRead):
        summed(None, shared)


def test_a_day_interval_refuses_to_end_before_it_starts():
    with pytest.raises(ValueError):
        DayInterval(date(2026, 3, 2), date(2026, 3, 1))


def test_a_window_of_no_days_refuses():
    with pytest.raises(ValueError, match="empty"):
        DayInterval.ending(date(2026, 3, 7), days=0)


def test_a_day_interval_ending_on_a_day_counts_that_day():
    assert DayInterval.ending(date(2026, 3, 7), days=7) == DayInterval(
        date(2026, 3, 1), date(2026, 3, 7)
    )
    assert DayInterval.single(date(2026, 3, 7)) == DayInterval(
        date(2026, 3, 7), date(2026, 3, 7)
    )


@pytest.mark.django_db
def test_a_year_narrows_the_per_game_sum(owned_library, game):
    day = date(2025, 6, 1)
    timed(owned_library, game, prague(10, day), prague(11, day))

    assert summed(owned_library, game, year=2025) == timedelta(hours=1)
    assert summed(owned_library, game, year=2026) is None


@pytest.mark.django_db
def test_platforms_order_by_playtime_then_name(owned_library):
    pc = Platform.objects.create(name="PC", icon="pc")
    switch = Platform.objects.create(name="Switch", icon="switch")
    day = date(2026, 3, 5)
    for platform, name, hours in (
        (switch, "Hades", 1),
        (pc, "Tunic", 1),
        (None, "Loose", 2),
    ):
        game = Game.objects.create(library=owned_library, name=name, platform=platform)
        timed(owned_library, game, prague(10, day), prague(10 + hours, day))

    assert playtime_by_platform(owned_library) == [
        PlatformPlaytime(None, None, tracked(timedelta(hours=2))),
        PlatformPlaytime(pc.pk, "PC", tracked(timedelta(hours=1))),
        PlatformPlaytime(switch.pk, "Switch", tracked(timedelta(hours=1))),
    ]


@pytest.mark.django_db
def test_the_sum_is_null_when_no_session_matches(owned_library, game):
    handheld = Device.objects.create(library=owned_library, name="Deck")
    started_at = datetime(2026, 3, 5, 10, tzinfo=UTC)
    timed(owned_library, game, started_at, started_at + timedelta(hours=1))

    matching = (
        Game.objects.filter(pk=game.pk)
        .annotate(
            figure=playtime_matching(
                owned_library, PlayerSessionFilter.where(device=[handheld.pk])
            )
        )
        .get()
        .figure
    )

    assert matching is None


HOUR = timedelta(hours=1)


@pytest.mark.django_db
def test_every_figure_adds_the_contained_records(owned_library, game, platform):
    day = date(2026, 3, 5)
    run = tracked_run(owned_library, game)
    timed(owned_library, game, prague(10, day), prague(11, day))
    record_row([run], duration=2 * HOUR, when="2026-03-05")
    record_row([run], duration=4 * HOUR, when="2026")
    record_row([run], duration=8 * HOUR, when=None)
    in_march = PlaytimeBreakdown(HOUR, 2 * HOUR)

    with timezone.override(TWIN_ZONE):
        assert game_playtime(owned_library, game) == PlaytimeBreakdown(HOUR, 14 * HOUR)
        assert total_playtime(owned_library) == PlaytimeBreakdown(HOUR, 14 * HOUR)
        assert total_playtime(owned_library, year=2026) == PlaytimeBreakdown(
            HOUR, 6 * HOUR
        )
        assert total_playtime(owned_library, year=2025) == PlaytimeBreakdown(ZERO, ZERO)
        assert playtime_between(owned_library, DayInterval.single(day)) == in_march
        assert (
            game_playtime_between(owned_library, game, DayInterval.single(day))
            == in_march
        )
        assert playtime_by_month(owned_library, year=2026) == [
            MonthPlaytime(date(2026, 3, 1), in_march)
        ]
        assert playtime_by_platform(owned_library, year=2026) == [
            PlatformPlaytime(platform.pk, "PC", PlaytimeBreakdown(HOUR, 6 * HOUR))
        ]


@pytest.mark.django_db
def test_both_windows_are_read_in_two_queries(
    owned_library, game, django_assert_num_queries
):
    day = date(2026, 3, 5)
    run = tracked_run(owned_library, game)
    timed(owned_library, game, prague(10, day), prague(11, day))
    record_row([run], duration=2 * HOUR, when="2026-03-01")
    week = DayInterval.ending(day, days=7)

    with timezone.override(TWIN_ZONE), django_assert_num_queries(2):
        figures = playtime_between_each(owned_library, [DayInterval.single(day), week])

    assert figures == [
        PlaytimeBreakdown(HOUR, ZERO),
        PlaytimeBreakdown(HOUR, 2 * HOUR),
    ]


@pytest.mark.django_db
def test_a_platform_or_month_only_records_reach_gets_a_row(owned_library, platform):
    recorded = Game.objects.create(
        library=owned_library, name="Tunic", platform=platform
    )
    record_row([tracked_run(owned_library, recorded)], duration=HOUR, when="2026-04")

    assert playtime_by_platform(owned_library) == [
        PlatformPlaytime(platform.pk, "PC", PlaytimeBreakdown(ZERO, HOUR))
    ]
    assert playtime_by_month(owned_library, year=2026) == [
        MonthPlaytime(date(2026, 4, 1), PlaytimeBreakdown(ZERO, HOUR))
    ]
    assert played_years(owned_library) == [2026]


@pytest.mark.django_db
def test_merged_platform_rows_keep_the_databases_order(owned_library):
    names = ["b", "a", None]
    for index, name in enumerate(names):
        platform = (
            None
            if name is None
            else Platform.objects.create(name=name, icon=f"icon-{index}")
        )
        played = Game.objects.create(
            library=owned_library, name=f"Game {index}", platform=platform
        )
        record_row([tracked_run(owned_library, played)], duration=HOUR, when=None)
    bigger = Game.objects.create(library=owned_library, name="Bigger")
    day = date(2026, 3, 5)
    timed(owned_library, bigger, prague(10, day), prague(13, day))

    rows = playtime_by_platform(owned_library)

    assert [row.platform_name for row in rows] == [None, "a", "b"]
    assert [row.playtime.total for row in rows] == [4 * HOUR, HOUR, HOUR]


@pytest.mark.django_db
def test_the_unspecified_platform_sorts_last_on_a_tie(owned_library):
    day = date(2026, 3, 5)
    for index, name in enumerate([None, "b", "a"]):
        platform = (
            None
            if name is None
            else Platform.objects.create(name=name, icon=f"icon-{index}")
        )
        played = Game.objects.create(
            library=owned_library, name=f"Game {index}", platform=platform
        )
        if index % 2:
            timed(owned_library, played, prague(10, day), prague(11, day))
        else:
            record_row([tracked_run(owned_library, played)], duration=HOUR, when=None)

    rows = playtime_by_platform(owned_library)

    assert [row.platform_name for row in rows] == ["a", "b", None]


@pytest.mark.django_db
def test_a_platform_renamed_between_reads_stays_one_row(owned_library, platform):
    day = date(2026, 3, 5)
    played = Game.objects.create(library=owned_library, name="Tunic", platform=platform)
    timed(owned_library, played, prague(10, day), prague(11, day))
    #: The second read sees an old name.
    renamed = [PlatformHistorical(platform.pk, "Old name", HOUR)]

    with patch("games.reads.playtime.historical_by_platform", return_value=renamed):
        rows = playtime_by_platform(owned_library)

    assert rows == [PlatformPlaytime(platform.pk, "PC", PlaytimeBreakdown(HOUR, HOUR))]


@pytest.mark.django_db
def test_the_sort_key_is_null_without_playtime(owned_library, game):
    running = Game.objects.create(library=owned_library, name="Running")
    recorded = Game.objects.create(library=owned_library, name="Recorded")
    timed(owned_library, running, prague(10, date(2026, 3, 5)), None)
    record_row([tracked_run(owned_library, recorded)], duration=HOUR, when=None)

    keys = dict(
        Game.objects.tracked_by(owned_library)
        .annotate(key=playtime_sort_key(owned_library))
        .values_list("name", "key")
    )

    assert keys == {"Outer Wilds": None, "Running": None, "Recorded": HOUR}


@pytest.mark.django_db
def test_the_playtime_filter_reads_the_composed_total(owned_library, game):
    day = date(2026, 3, 5)
    timed(owned_library, game, prague(10, day), prague(11, day))
    record_row([tracked_run(owned_library, game)], duration=2 * HOUR, when=None)
    sessions_only = Game.objects.create(library=owned_library, name="Sessions")
    timed(owned_library, sessions_only, prague(10, day), prague(12, day))
    records_only = Game.objects.create(library=owned_library, name="Records")
    record_row([tracked_run(owned_library, records_only)], duration=2 * HOUR, when=None)
    over_two_hours = GameFilter.from_json(
        {"playtime_hours": {"modifier": "GREATER_THAN", "value": 2}}
    )
    context = filter_query_context_for_library(owned_library)

    matched = execute_filter(
        over_two_hours, Game.objects.tracked_by(owned_library), context
    )

    assert list(matched) == [game]


@pytest.mark.django_db
def test_a_session_filter_never_reaches_records(owned_library, game):
    handheld = Device.objects.create(library=owned_library, name="Deck")
    run = tracked_run(owned_library, game)
    timed_row(
        run,
        datetime(2026, 3, 5, 10, tzinfo=UTC),
        datetime(2026, 3, 5, 11, tzinfo=UTC),
        device=handheld,
    )
    record_row([run], duration=2 * HOUR, when=None, device=handheld)

    figure = (
        Game.objects.filter(pk=game.pk)
        .annotate(
            matching=playtime_matching(
                owned_library, PlayerSessionFilter.where(device=[handheld.pk])
            )
        )
        .get()
        .matching
    )

    assert figure == HOUR


@pytest.mark.django_db
def test_a_composed_sum_over_no_library_refuses_to_execute(game):
    with pytest.raises(UnscopedPlaytimeRead):
        list(Game.objects.annotate(figure=playtime_by_game(None)))
    unscoped = Game.objects.annotate(figure=playtime_sort_key(None))  # type: ignore[arg-type]
    with pytest.raises(UnscopedPlaytimeRead):
        list(unscoped)


@pytest.mark.django_db
def test_a_python_figure_without_a_library_refuses(game):
    with pytest.raises(UnscopedRead):
        total_playtime(None)  # type: ignore[arg-type]
    with pytest.raises(UnscopedRead):
        game_playtime(None, game)  # type: ignore[arg-type]


def test_no_window_reads_nothing(owned_library, django_assert_num_queries):
    with django_assert_num_queries(0):
        assert playtime_between_each(owned_library, []) == []


@pytest.mark.django_db
def test_the_games_tracked_window_leaves_records_out(owned_library, game):
    day = date(2026, 3, 5)
    run = tracked_run(owned_library, game)
    timed(owned_library, game, prague(10, day), prague(11, day))
    record_row([run], duration=2 * HOUR, when="2026-03-05")
    days = DayInterval.single(day)

    with timezone.override(TWIN_ZONE):
        assert game_tracked_between(owned_library, game, days) == HOUR
        assert game_playtime_between(owned_library, game, days).total == 3 * HOUR


def test_a_source_that_repeats_a_key_refuses():
    with pytest.raises(ValueError, match="twice"):
        _merged([("a", HOUR), ("a", HOUR)], [])


def test_the_breakdown_is_importable_from_both_modules():
    """The value lives beside the sums; playtime re-exports it."""
    from games.reads.playtime import PlaytimeBreakdown as from_playtime
    from games.reads.sums import PlaytimeBreakdown as from_sums

    assert from_playtime is from_sums
