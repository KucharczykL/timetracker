"""Historical playtime records, read beside sessions."""

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone
from record_rows import record_row
from session_rows import tracked_run

from games.models import Device, Game, HistoricalPlaytime, PlayerGame, UserLibrary
from games.reads.historical_playtime_records import (
    game_records,
    library_records,
    readable_records,
)
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
