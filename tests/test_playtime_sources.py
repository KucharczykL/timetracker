"""Playtime read from the session projection."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone
from session_rows import (
    TWIN_ZONE,
    corrected_row,
    duration_only_row,
    timed_row,
    tracked_run,
)

from games.filters import PlayerSessionFilter
from games.models import Device, Game, Platform, UserLibrary
from games.reads.playtime import (
    DayInterval,
    MonthPlaytime,
    PlatformPlaytime,
    UnscopedPlaytimeRead,
    game_playtime,
    game_playtime_between,
    played_years,
    playtime_between,
    playtime_by_game,
    playtime_by_month,
    playtime_by_platform,
    playtime_matching,
    playtime_sort_key,
    summed_by_game,
    summed_by_game_matching,
    total_playtime,
)

ZERO = timedelta(0)


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
        .annotate(figure=summed_by_game(library, **scope))
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
    assert game_playtime(owned_library, game) == ZERO
    assert game_playtime_between(owned_library, game, days) == ZERO
    assert total_playtime(owned_library) == ZERO
    assert total_playtime(owned_library, year=2026) == ZERO
    assert playtime_between(owned_library, days) == ZERO
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
            matching=playtime_matching(owned_library, None),
            by_game=playtime_by_game(owned_library),
        )
        .get()
    )

    assert figures.sort_key is None
    assert figures.matching is None
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
            "game": game_playtime(owned_library, game),
            "summed": summed(owned_library, game),
            "summed in year": summed(owned_library, game, year=2026),
            "total": total_playtime(owned_library),
            "total in year": total_playtime(owned_library, year=2026),
            "between": playtime_between(owned_library, DayInterval.single(day)),
            "game between": game_playtime_between(
                owned_library, game, DayInterval.single(day)
            ),
            "platforms": playtime_by_platform(owned_library),
            "platforms in year": playtime_by_platform(owned_library, year=2026),
            "months": playtime_by_month(owned_library, year=2026),
            "years": played_years(owned_library),
        }

    #: A Corrected row's stated time replaces its elapsed time.
    assert figures == {
        "game": total,
        "summed": total,
        "summed in year": total,
        "total": total,
        "total in year": total,
        "between": timedelta(hours=2, minutes=30),
        "game between": timedelta(hours=2, minutes=30),
        "platforms": [PlatformPlaytime(platform.pk, "PC", total)],
        "platforms in year": [PlatformPlaytime(platform.pk, "PC", total)],
        "months": [
            MonthPlaytime(date(2026, 3, 1), timedelta(hours=2, minutes=30)),
            MonthPlaytime(date(2026, 4, 1), timedelta(minutes=90)),
        ],
        "years": [2026],
    }


@pytest.mark.django_db
def test_a_running_timed_row_counts_zero(owned_library, game):
    started_at = prague(10, date(2026, 3, 5))
    timed(owned_library, game, started_at, None)

    with timezone.override(TWIN_ZONE):
        assert game_playtime(owned_library, game) == ZERO
        assert (
            game_playtime_between(
                owned_library, game, DayInterval.single(started_at.date())
            )
            == ZERO
        )
        assert total_playtime(owned_library) == ZERO
        assert total_playtime(owned_library, year=2026) == ZERO


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
            assert total_playtime(owned_library, year=2026) == timedelta(minutes=20)
            assert total_playtime(owned_library, year=2025) == ZERO
            assert played_years(owned_library) == [2026]


@pytest.mark.django_db
def test_a_duration_only_row_lands_on_its_written_day(owned_library, game):
    day = date(2026, 3, 5)
    duration = timedelta(minutes=90)
    duration_only_row(tracked_run(owned_library, game), day, duration)

    with timezone.override(TWIN_ZONE):
        assert total_playtime(owned_library, year=2026) == duration
        assert playtime_by_month(owned_library, year=2026) == [
            MonthPlaytime(date(2026, 3, 1), duration)
        ]
        assert playtime_between(owned_library, DayInterval.single(day)) == duration
        assert (
            playtime_between(owned_library, DayInterval.single(day + timedelta(days=1)))
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
        assert playtime_between(owned_library, DayInterval(first, last)) == 2 * inside


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
        figure = game_playtime_between(owned_library, game, DayInterval(first, last))

    assert figure == 4 * inside


@pytest.mark.django_db
def test_a_games_window_never_counts_another_library(owned_library, stranger_library):
    shared = Game.objects.create(library=None, name="Tetris")
    started_at = datetime(2026, 3, 5, 10, tzinfo=UTC)
    days = DayInterval.single(started_at.date())
    for library, hours in ((owned_library, 1), (stranger_library, 2)):
        ended_at = started_at + timedelta(hours=hours)
        timed_row(tracked_run(library, shared), started_at, ended_at)

    assert game_playtime_between(owned_library, shared, days) == timedelta(hours=1)
    assert game_playtime_between(stranger_library, shared, days) == timedelta(hours=2)


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
            matching=summed_by_game_matching(owned_library, on_the_handheld),
            filtered=playtime_matching(owned_library, on_the_handheld),
            unfiltered=playtime_matching(owned_library, None),
        )
        .get()
    )

    assert figures.matching == timedelta(hours=1)
    assert figures.filtered == timedelta(hours=1)
    assert figures.unfiltered == total_playtime(owned_library)
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
        PlatformPlaytime(None, None, timedelta(hours=2)),
        PlatformPlaytime(pc.pk, "PC", timedelta(hours=1)),
        PlatformPlaytime(switch.pk, "Switch", timedelta(hours=1)),
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
