"""The records a library counts."""

import uuid
from datetime import timedelta

import pytest

from games.commands.historical_playtime import (
    HistoricalPlaytimeStatement,
    RecordHistoricalPlaytime,
    RemoveHistoricalPlaytime,
)
from games.commands.playergame import RemovePlayerGame
from games.events.dispatch import dispatch
from games.models import (
    Game,
    HistoricalPlaytime,
    HistoricalPlaytimeProvenance,
    Playthrough,
)
from games.reads.historical_playtime_records import (
    RECORD_ORDER,
    game_records,
    library_records,
    readable_records,
)
from games.removal import remove

pytestmark = pytest.mark.django_db(transaction=True)


def _record(user, game: Game, when: str | None = "2005") -> HistoricalPlaytime:
    run = Playthrough.objects.get(player_game__game=game)
    dispatch(
        RecordHistoricalPlaytime(
            statement=HistoricalPlaytimeStatement(
                duration=timedelta(hours=10),
                when=when,
                provenance=HistoricalPlaytimeProvenance.ESTIMATED,
                playthrough_ids=(run.pk,),
                device_id=None,
                emulated=False,
                note="",
            )
        ),
        actor=user,
        library=user.library,
        idempotency_key=str(uuid.uuid7()),
    )
    return HistoricalPlaytime.objects.latest("created_at")


@pytest.fixture
def game(owned_library):
    return Game.objects.create(library=owned_library, name="Outer Wilds")


def test_a_live_record_is_counted(owned_user, owned_library, game):
    record = _record(owned_user, game)
    assert list(library_records(owned_library)) == [record]


def test_a_removed_record_is_not(owned_user, owned_library, game):
    record = _record(owned_user, game)
    dispatch(
        RemoveHistoricalPlaytime(record_id=record.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="remove",
    )
    assert not library_records(owned_library).exists()


def test_a_record_of_an_untracked_game_is_not(owned_user, owned_library, game):
    _record(owned_user, game)
    dispatch(
        RemovePlayerGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="untrack",
    )
    assert not library_records(owned_library).exists()


def test_a_record_of_a_removed_catalog_game_is_not(owned_user, owned_library, game):
    record = _record(owned_user, game)
    remove(game)
    #: The mark alive() does not read.
    assert HistoricalPlaytime.objects.alive().filter(pk=record.pk).exists()
    assert not library_records(owned_library).exists()
    assert not readable_records(owned_library).exists()


def test_another_librarys_record_is_not(
    owned_user, owned_library, game, django_user_model
):
    _record(owned_user, game)
    other = django_user_model.objects.create_user(username="someone-else")
    assert not library_records(other.library).exists()


def test_game_records_narrows_to_one_game(owned_user, owned_library, game):
    other_game = Game.objects.create(library=owned_library, name="Tunic")
    record = _record(owned_user, game)
    _record(owned_user, other_game)
    assert list(game_records(owned_library, game)) == [record]


def test_the_order_is_newest_when_then_unknown_then_newest_recorded(
    owned_user, owned_library, game
):
    older = _record(owned_user, game, "2005")
    unknown = _record(owned_user, game, None)
    newer = _record(owned_user, game, "2010")
    same_when_later = _record(owned_user, game, "2005")
    ordered = list(library_records(owned_library).order_by(*RECORD_ORDER))
    assert ordered == [newer, same_when_later, older, unknown]
