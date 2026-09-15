"""Playtime read from either session table."""

from datetime import UTC, date, datetime, time, timedelta
from types import ModuleType
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone
from session_rows import (
    TWIN_ZONE,
    corrected_twin,
    duration_only_twin,
    timed_row,
    timed_twin,
    tracked_run,
)

import games.reads.playtime
from games.filters import SessionFilter
from games.models import Device, Game, Platform, Session, UserLibrary
from games.reads.playtime import (
    DayInterval,
    MonthPlaytime,
    PlatformPlaytime,
    UnscopedPlaytimeRead,
    game_playtime,
    game_playtime_between,
    legacy,
    playtime_between,
    playtime_by_game,
    playtime_by_month,
    playtime_by_platform,
    playtime_matching,
    playtime_sort_key,
    projection,
    total_playtime,
)

ZERO = timedelta(0)
SOURCES = pytest.mark.parametrize(
    "source", [legacy, projection], ids=["legacy", "projection"]
)


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


def summed(source: ModuleType, library: UserLibrary | None, game: Game, **scope):
    """The source's sum on one game."""
    return (
        Game.objects.filter(pk=game.pk)
        .annotate(figure=source.summed_by_game(library, **scope))
        .get()
        .figure
    )


def prague(hour: int, day: date) -> datetime:
    return datetime.combine(day, time(hour), tzinfo=TWIN_ZONE)


@pytest.mark.django_db
def test_every_scalar_figure_is_zero_for_an_empty_library(owned_library, game):
    days = DayInterval(date(2026, 1, 1), date(2026, 12, 31))
    for source in (legacy, projection):
        assert source.game_playtime(owned_library, game) == ZERO
        assert source.game_playtime_between(owned_library, game, days) == ZERO
        assert source.total_playtime(owned_library) == ZERO
        assert source.total_playtime(owned_library, year=2026) == ZERO
        assert source.playtime_between(owned_library, days) == ZERO
        assert source.playtime_by_platform(owned_library) == []
        assert source.playtime_by_month(owned_library, year=2026) == []
        assert source.played_years(owned_library) == []
    assert game_playtime(owned_library, game) == ZERO
    assert game_playtime_between(owned_library, game, days) == ZERO
    assert total_playtime(owned_library) == ZERO
    assert total_playtime(owned_library, year=2026) == ZERO
    assert playtime_between(owned_library, days) == ZERO
    assert playtime_by_platform(owned_library) == []
    assert playtime_by_month(owned_library, year=2026) == []


@pytest.mark.django_db
@SOURCES
def test_each_source_sums_an_unplayed_game_to_null(source, owned_library, game):
    assert summed(source, owned_library, game) is None


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
def test_a_twin_of_each_mode_gives_equal_figures(owned_library, game, platform):
    day = date(2026, 3, 5)
    timed_twin(owned_library, game, prague(10, day), prague(12, day))
    duration_only_twin(owned_library, game, date(2026, 4, 2), timedelta(minutes=90))
    corrected_twin(
        owned_library,
        game,
        prague(20, day),
        prague(21, day),
        timedelta(minutes=30),
    )
    total = timedelta(hours=5)

    def figures(source: ModuleType) -> dict[str, object]:
        with timezone.override(TWIN_ZONE):
            return {
                "game": source.game_playtime(owned_library, game),
                "summed": summed(source, owned_library, game),
                "summed in year": summed(source, owned_library, game, year=2026),
                "total": source.total_playtime(owned_library),
                "total in year": source.total_playtime(owned_library, year=2026),
                "between": source.playtime_between(
                    owned_library, DayInterval.single(day)
                ),
                "game between": source.game_playtime_between(
                    owned_library, game, DayInterval.single(day)
                ),
                "platforms": source.playtime_by_platform(owned_library),
                "platforms in year": source.playtime_by_platform(
                    owned_library, year=2026
                ),
                "months": source.playtime_by_month(owned_library, year=2026),
                "years": source.played_years(owned_library),
            }

    assert figures(legacy) == figures(projection)
    assert figures(legacy) == {
        "game": total,
        "summed": total,
        "summed in year": total,
        "total": total,
        "total in year": total,
        "between": timedelta(hours=3, minutes=30),
        "game between": timedelta(hours=3, minutes=30),
        "platforms": [PlatformPlaytime(platform.pk, "PC", total)],
        "platforms in year": [PlatformPlaytime(platform.pk, "PC", total)],
        "months": [
            MonthPlaytime(date(2026, 3, 1), timedelta(hours=3, minutes=30)),
            MonthPlaytime(date(2026, 4, 1), timedelta(minutes=90)),
        ],
        "years": [2026],
    }


@SOURCES
@pytest.mark.django_db
def test_a_running_timed_row_counts_zero(source, owned_library, game):
    started_at = prague(10, date(2026, 3, 5))
    timed_twin(owned_library, game, started_at, None)

    with timezone.override(TWIN_ZONE):
        assert source.game_playtime(owned_library, game) == ZERO
        assert (
            source.game_playtime_between(
                owned_library, game, DayInterval.single(started_at.date())
            )
            == ZERO
        )
        assert source.total_playtime(owned_library) == ZERO
        assert source.total_playtime(owned_library, year=2026) == ZERO


@pytest.mark.django_db
def test_the_projection_reads_the_stored_day(owned_library, game):
    started_at = datetime(2025, 12, 31, 23, 30, tzinfo=UTC)
    timed_row(
        tracked_run(owned_library, game),
        started_at,
        started_at + timedelta(minutes=20),
        day_zone="Europe/Prague",
    )

    for zone in (TWIN_ZONE, ZoneInfo("UTC")):
        with timezone.override(zone):
            assert projection.total_playtime(owned_library, year=2026) == timedelta(
                minutes=20
            )
            assert projection.total_playtime(owned_library, year=2025) == ZERO
            assert projection.played_years(owned_library) == [2026]


@SOURCES
@pytest.mark.django_db
def test_a_duration_only_row_lands_on_its_written_day(source, owned_library, game):
    day = date(2026, 3, 5)
    duration = timedelta(minutes=90)
    duration_only_twin(owned_library, game, day, duration)

    with timezone.override(TWIN_ZONE):
        assert source.total_playtime(owned_library, year=2026) == duration
        assert source.playtime_by_month(owned_library, year=2026) == [
            MonthPlaytime(date(2026, 3, 1), duration)
        ]
        assert (
            source.playtime_between(owned_library, DayInterval.single(day)) == duration
        )
        assert (
            source.playtime_between(
                owned_library, DayInterval.single(day + timedelta(days=1))
            )
            == ZERO
        )


@pytest.mark.django_db
def test_the_legacy_source_reads_the_active_zone(owned_library, game):
    started_at = datetime(2025, 12, 31, 23, 30, tzinfo=UTC)
    Session.objects.create(
        game=game,
        timestamp_start=started_at,
        timestamp_end=started_at + timedelta(minutes=20),
    )

    with timezone.override(ZoneInfo("UTC")):
        assert legacy.total_playtime(owned_library, year=2025) == timedelta(minutes=20)
        assert legacy.played_years(owned_library) == [2025]
    with timezone.override(TWIN_ZONE):
        assert legacy.total_playtime(owned_library, year=2026) == timedelta(minutes=20)
        assert legacy.played_years(owned_library) == [2026]


@SOURCES
@pytest.mark.django_db
def test_a_day_window_is_inclusive(source, owned_library, game):
    first, last = date(2026, 3, 5), date(2026, 3, 7)
    inside = timedelta(minutes=10)
    outside = timedelta(minutes=1)
    before_first = datetime.combine(first, time(0), tzinfo=TWIN_ZONE)
    timed_twin(owned_library, game, before_first, before_first + inside)
    late_on_last = datetime.combine(last, time(23, 30), tzinfo=TWIN_ZONE)
    timed_twin(owned_library, game, late_on_last, late_on_last + inside)
    timed_twin(
        owned_library,
        game,
        before_first - timedelta(minutes=5),
        before_first - timedelta(minutes=4),
    )
    after_last = datetime.combine(last + timedelta(days=1), time(0), tzinfo=TWIN_ZONE)
    timed_twin(owned_library, game, after_last, after_last + outside)

    with timezone.override(TWIN_ZONE):
        assert (
            source.playtime_between(owned_library, DayInterval(first, last))
            == 2 * inside
        )


@SOURCES
@pytest.mark.django_db
def test_a_games_window_counts_that_game_alone(source, owned_library, game):
    """One game, inclusive days, in the library's calendar."""
    first, last = date(2026, 3, 5), date(2026, 3, 7)
    inside = timedelta(minutes=10)
    other = Game.objects.create(library=owned_library, name="Tunic")
    on_first = datetime.combine(first, time(0), tzinfo=TWIN_ZONE)
    timed_twin(owned_library, game, on_first, on_first + inside)
    late_on_last = datetime.combine(last, time(23, 30), tzinfo=TWIN_ZONE)
    timed_twin(owned_library, game, late_on_last, late_on_last + inside)
    duration_only_twin(owned_library, game, last, inside)
    corrected_twin(owned_library, game, on_first, on_first + inside, inside)
    timed_twin(owned_library, other, on_first, on_first + inside)
    before = on_first - timedelta(minutes=5)
    timed_twin(owned_library, game, before, before + inside)
    after = datetime.combine(last + timedelta(days=1), time(0), tzinfo=TWIN_ZONE)
    timed_twin(owned_library, game, after, after + inside)

    with timezone.override(TWIN_ZONE):
        figure = source.game_playtime_between(
            owned_library, game, DayInterval(first, last)
        )

    assert figure == 5 * inside


@pytest.mark.django_db
def test_a_games_window_never_counts_another_library(owned_library, stranger_library):
    shared = Game.objects.create(library=None, name="Tetris")
    started_at = datetime(2026, 3, 5, 10, tzinfo=UTC)
    days = DayInterval.single(started_at.date())
    for library, hours in ((owned_library, 1), (stranger_library, 2)):
        ended_at = started_at + timedelta(hours=hours)
        timed_row(tracked_run(library, shared), started_at, ended_at)

    assert projection.game_playtime_between(owned_library, shared, days) == timedelta(
        hours=1
    )
    assert projection.game_playtime_between(
        stranger_library, shared, days
    ) == timedelta(hours=2)


@SOURCES
@pytest.mark.django_db
def test_summed_by_game_never_counts_another_library(
    source, owned_library, stranger_library
):
    shared = Game.objects.create(library=None, name="Tetris")
    started_at = datetime(2026, 3, 5, 10, tzinfo=UTC)
    for library, hours in ((owned_library, 1), (stranger_library, 2)):
        ended_at = started_at + timedelta(hours=hours)
        Session.objects.create(
            game=shared, timestamp_start=started_at, timestamp_end=ended_at
        )
        timed_row(tracked_run(library, shared), started_at, ended_at)

    #: Legacy counts shared-catalog sessions in no library.
    expected = {
        legacy: (None, None),
        projection: (timedelta(hours=1), timedelta(hours=2)),
    }
    assert (
        summed(source, owned_library, shared),
        summed(source, stranger_library, shared),
    ) == expected[source]


@pytest.mark.django_db
def test_the_legacy_source_honours_a_session_filter(owned_library, game):
    handheld = Device.objects.create(library=owned_library, name="Deck")
    desktop = Device.objects.create(library=owned_library, name="Tower")
    started_at = datetime(2026, 3, 5, 10, tzinfo=UTC)
    for device, hours in ((handheld, 1), (desktop, 2)):
        Session.objects.create(
            game=game,
            device=device,
            timestamp_start=started_at,
            timestamp_end=started_at + timedelta(hours=hours),
        )
    on_the_handheld = SessionFilter.where(device=[handheld.pk])

    figures = (
        Game.objects.filter(pk=game.pk)
        .annotate(
            matching=legacy.summed_by_game_matching(owned_library, on_the_handheld),
            filtered=playtime_matching(owned_library, on_the_handheld),
            unfiltered=playtime_matching(owned_library, None),
        )
        .get()
    )

    assert figures.matching == timedelta(hours=1)
    assert figures.filtered == timedelta(hours=1)
    assert figures.unfiltered == legacy.total_playtime(owned_library)
    assert figures.unfiltered == timedelta(hours=3)


@SOURCES
@pytest.mark.django_db
def test_summed_by_game_over_no_library_refuses_to_execute(source, stranger_library):
    shared = Game.objects.create(library=None, name="Tetris")
    started_at = datetime(2026, 3, 5, 10, tzinfo=UTC)
    ended_at = started_at + timedelta(hours=1)
    Session.objects.create(
        game=shared, timestamp_start=started_at, timestamp_end=ended_at
    )
    timed_row(tracked_run(stranger_library, shared), started_at, ended_at)

    #: The trap a passed-on None hits.
    assert Session.objects.for_library(None).filter(game=shared).exists()
    with pytest.raises(UnscopedPlaytimeRead):
        summed(source, None, shared)


def test_the_package_answers_from_the_legacy_source():
    assert games.reads.playtime.SOURCE is legacy


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


@SOURCES
@pytest.mark.django_db
def test_a_year_narrows_the_per_game_sum(source, owned_library, game):
    day = date(2025, 6, 1)
    timed_twin(owned_library, game, prague(10, day), prague(11, day))

    assert summed(source, owned_library, game, year=2025) == timedelta(hours=1)
    assert summed(source, owned_library, game, year=2026) is None


@SOURCES
@pytest.mark.django_db
def test_platforms_order_by_playtime_then_name(source, owned_library):
    pc = Platform.objects.create(name="PC", icon="pc")
    switch = Platform.objects.create(name="Switch", icon="switch")
    day = date(2026, 3, 5)
    for platform, name, hours in (
        (switch, "Hades", 1),
        (pc, "Tunic", 1),
        (None, "Loose", 2),
    ):
        game = Game.objects.create(library=owned_library, name=name, platform=platform)
        timed_twin(owned_library, game, prague(10, day), prague(10 + hours, day))

    assert source.playtime_by_platform(owned_library) == [
        PlatformPlaytime(None, None, timedelta(hours=2)),
        PlatformPlaytime(pc.pk, "PC", timedelta(hours=1)),
        PlatformPlaytime(switch.pk, "Switch", timedelta(hours=1)),
    ]


@pytest.mark.django_db
def test_the_sum_is_null_when_no_session_matches(owned_library, game):
    handheld = Device.objects.create(library=owned_library, name="Deck")
    started_at = datetime(2026, 3, 5, 10, tzinfo=UTC)
    Session.objects.create(
        game=game,
        timestamp_start=started_at,
        timestamp_end=started_at + timedelta(hours=1),
    )

    matching = (
        Game.objects.filter(pk=game.pk)
        .annotate(
            figure=playtime_matching(
                owned_library, SessionFilter.where(device=[handheld.pk])
            )
        )
        .get()
        .figure
    )

    assert matching is None
