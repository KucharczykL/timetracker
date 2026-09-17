"""Historical playtime records, read beside sessions."""

import uuid
from datetime import date, timedelta

import pytest
from django.utils import timezone
from record_rows import record_join, record_row
from session_rows import tracked_run

from games.models import (
    Device,
    Game,
    HistoricalPlaytime,
    HistoricalPlaytimeProvenance,
    Platform,
    PlayerGame,
    Playthrough,
    PlaythroughKind,
    UserLibrary,
)
from games.reads.days import DayInterval
from games.reads.historical_playtime import (
    MonthHistorical,
    PlatformHistorical,
    game_historical_playtime,
    historical_by_month,
    historical_by_platform,
    historical_summed_by_game,
    historical_total,
    historical_totals,
    historical_years,
)
from games.reads.historical_playtime_records import (
    game_records,
    library_records,
    readable_records,
)
from games.reads.sums import UnscopedPlaytimeRead
from games.removal import remove

HOUR = timedelta(hours=1)


@pytest.fixture
def game(owned_library) -> Game:
    return Game.objects.create(library=owned_library, name="Outer Wilds")


@pytest.fixture
def run(owned_library, game):
    return tracked_run(owned_library, game)


@pytest.fixture
def stranger_library(django_user_model) -> UserLibrary:
    return django_user_model.objects.create_user(
        username="stranger", password="p"
    ).library


def counted(library: UserLibrary) -> list[HistoricalPlaytime]:
    return list(library_records(library))


@pytest.mark.django_db
def test_a_live_record_is_counted(owned_library, run):
    record = record_row(run, duration=HOUR, when="2022")
    assert counted(owned_library) == [record]


@pytest.mark.django_db
def test_another_librarys_record_is_not_counted(owned_library, stranger_library):
    foreign = Game.objects.create(library=stranger_library, name="Tunic")
    record_row(tracked_run(stranger_library, foreign), duration=HOUR, when="2022")
    assert counted(owned_library) == []


@pytest.mark.django_db
def test_a_record_naming_another_librarys_tracked_game_is_not_counted(
    owned_library, stranger_library
):
    foreign = Game.objects.create(library=stranger_library, name="Tunic")
    foreign_run = tracked_run(stranger_library, foreign)
    #: Drift the ownership audit reports.
    record_row(foreign_run, duration=HOUR, when="2022", library=owned_library)
    assert counted(owned_library) == []


@pytest.mark.django_db
def test_a_removed_record_is_not_counted(owned_library, run):
    record = record_row(run, duration=HOUR, when="2022")
    HistoricalPlaytime.objects.filter(pk=record.pk).update(removed_at=timezone.now())
    assert counted(owned_library) == []


@pytest.mark.django_db
def test_a_record_of_a_removed_tracked_game_is_not_counted(owned_library, run):
    record_row(run, duration=HOUR, when="2022")
    PlayerGame.objects.filter(pk=run.player_game_id).update(removed_at=timezone.now())
    assert counted(owned_library) == []


@pytest.mark.django_db
def test_a_record_of_a_removed_catalog_game_is_not_counted(owned_library, game, run):
    record_row(run, duration=HOUR, when="2022")
    remove(game)
    assert counted(owned_library) == []


@pytest.mark.django_db
def test_game_records_narrow_to_one_catalog_game(owned_library, game, run):
    other = Game.objects.create(library=owned_library, name="Tunic")
    mine = record_row(run, duration=HOUR, when="2022")
    record_row(tracked_run(owned_library, other), duration=HOUR, when="2022")
    assert list(game_records(owned_library, game)) == [mine]


@pytest.mark.django_db
def test_readable_records_read_platform_and_device_at_once(
    owned_library, run, django_assert_num_queries
):
    device = Device.objects.create(library=owned_library, name="Deck")
    record_row(run, duration=HOUR, when="2022", device=device)
    with django_assert_num_queries(1):
        (record,) = readable_records(owned_library)
        assert record.player_game.game.platform is None
        assert record.device == device


@pytest.mark.django_db
def test_an_unused_id_is_never_counted(owned_library, run):
    record_row(run, duration=HOUR, when="2022")
    assert not library_records(owned_library).filter(pk=uuid.uuid7()).exists()


YEAR = DayInterval.year(2022)
JUNE = DayInterval.month(2022, 6)
DAY = DayInterval.single(date(2022, 6, 11))

#: Which scopes a record with this `when` counts in.
CONTAINMENT = [
    ("2022", {"year", "all"}),
    ("2022~", {"year", "all"}),
    ("2022-06", {"year", "month", "all"}),
    ("2022-06-11", {"year", "month", "day", "all"}),
    ("2022-06-11/2022-06-20", {"year", "month", "all"}),
    ("2020/2022", {"all"}),
    ("202X", {"all"}),
    ("../2021-09-27", {"all"}),
    ("2020/", {"all"}),
    ("2020/..", {"all"}),
    (None, {"all"}),
]


@pytest.mark.django_db
@pytest.mark.parametrize(("when", "scopes"), CONTAINMENT)
def test_a_record_counts_where_its_when_lies_wholly(owned_library, run, when, scopes):
    record_row(run, duration=HOUR, when=when)
    counted_in = {
        name
        for name, within in {
            "year": YEAR,
            "month": JUNE,
            "day": DAY,
            "all": None,
        }.items()
        if historical_total(owned_library, within=within) == HOUR
    }
    assert counted_in == scopes


@pytest.mark.django_db
@pytest.mark.parametrize(("when", "scopes"), CONTAINMENT)
def test_the_month_rows_count_what_lies_in_one_month(owned_library, run, when, scopes):
    record_row(run, duration=HOUR, when=when)
    expected = [MonthHistorical(date(2022, 6, 1), HOUR)] if "month" in scopes else []
    assert historical_by_month(owned_library, year=2022) == expected


@pytest.mark.django_db
@pytest.mark.parametrize(("when", "scopes"), CONTAINMENT)
def test_a_year_is_listed_when_it_holds_a_record(owned_library, run, when, scopes):
    record_row(run, duration=HOUR, when=when)
    assert historical_years(owned_library) == ([2022] if "year" in scopes else [])


@pytest.mark.django_db
def test_one_query_sums_every_window(owned_library, run, django_assert_num_queries):
    record_row(run, duration=HOUR, when="2022-06-11")
    record_row(run, duration=2 * HOUR, when="2022-06")
    with django_assert_num_queries(1):
        totals = historical_totals(owned_library, [DAY, JUNE, YEAR])
    assert totals == [HOUR, 3 * HOUR, 3 * HOUR]
    assert historical_totals(owned_library, []) == []


@pytest.mark.django_db
def test_a_record_reaches_its_platform_through_the_game(owned_library):
    platform = Platform.objects.create(name="PC", icon="pc")
    played = Game.objects.create(library=owned_library, name="Tunic", platform=platform)
    unplaced = Game.objects.create(library=owned_library, name="Outer Wilds")
    record_row(tracked_run(owned_library, played), duration=HOUR, when="2022")
    record_row(tracked_run(owned_library, unplaced), duration=2 * HOUR, when="2021")

    assert sorted(historical_by_platform(owned_library), key=str) == sorted(
        [
            PlatformHistorical(platform.pk, "PC", HOUR),
            PlatformHistorical(None, None, 2 * HOUR),
        ],
        key=str,
    )
    assert historical_by_platform(owned_library, within=YEAR) == [
        PlatformHistorical(platform.pk, "PC", HOUR)
    ]


@pytest.mark.django_db
def test_provenance_narrows_the_games_sum(owned_library, game, run):
    record_row(run, duration=HOUR, when="2022")
    record_row(
        run,
        duration=2 * HOUR,
        when=None,
        provenance=HistoricalPlaytimeProvenance.EXTERNALLY_MEASURED,
    )
    assert game_historical_playtime(owned_library, game) == 3 * HOUR
    assert (
        game_historical_playtime(
            owned_library, game, HistoricalPlaytimeProvenance.EXTERNALLY_MEASURED
        )
        == 2 * HOUR
    )


@pytest.mark.django_db
def test_the_per_game_sum_agrees_with_the_games_figure(owned_library, game, run):
    unplayed = Game.objects.create(library=owned_library, name="Tunic")
    record_row(run, duration=HOUR, when="2022")
    record_row(run, duration=HOUR, when="2019")
    sums = dict(
        Game.objects.filter(pk__in=[game.pk, unplayed.pk])
        .annotate(
            all_time=historical_summed_by_game(owned_library),
            in_year=historical_summed_by_game(owned_library, within=YEAR),
        )
        .values_list("pk", "all_time")
    )
    assert sums == {
        game.pk: game_historical_playtime(owned_library, game),
        unplayed.pk: None,
    }
    assert (
        Game.objects.filter(pk=game.pk)
        .annotate(in_year=historical_summed_by_game(owned_library, within=YEAR))
        .get()
        .in_year
        == HOUR
    )


@pytest.mark.django_db
def test_an_unscoped_per_game_sum_refuses_to_execute(game):
    games = Game.objects.annotate(figure=historical_summed_by_game(None))
    with pytest.raises(UnscopedPlaytimeRead):
        list(games)


@pytest.mark.django_db
def test_a_record_naming_two_runs_counts_once(owned_library, game, run):
    second = Playthrough.objects.create(
        pk=uuid.uuid7(),
        library=owned_library,
        player_game=run.player_game,
        kind=PlaythroughKind.ORDINARY,
        created_at=timezone.now(),
    )
    record = record_row(run, duration=HOUR, when="2022")
    record_join(record, second)
    assert historical_total(owned_library) == HOUR
    assert game_historical_playtime(owned_library, game) == HOUR
