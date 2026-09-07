"""The run a converted legacy row became."""

import uuid

import pytest

from games.backfill.playthrough import convert_library
from games.events.playthrough import PLAYTHROUGH_CREATED
from games.models import Game, LibraryEvent, PlayEvent
from games.reads.playthrough_provenance import (
    NEVER_CONVERTED,
    RUN_UNREADABLE,
    run_for_row,
    runs_for_rows,
)


@pytest.fixture
def user(owned_user):
    return owned_user


@pytest.fixture
def game(owned_library):
    return Game.objects.create(library=owned_library, name="Outer Wilds")


@pytest.mark.django_db(transaction=True)
def test_a_converted_row_maps_to_its_run(user, game):
    row = PlayEvent.objects.create(game=game, started=None, ended=None, note="")
    convert_library(user.library)

    converted = run_for_row(user.library, row.pk)

    assert converted.run is not None
    assert converted.run.player_game.game_id == game.pk
    assert not converted.never_converted


@pytest.mark.django_db(transaction=True)
def test_a_row_the_conversion_never_saw_maps_to_nothing(user, game):
    row = PlayEvent.objects.create(game=game, started=None, ended=None, note="")

    converted = run_for_row(user.library, row.pk)

    assert converted.run is None
    assert converted.never_converted
    assert converted.sentence == NEVER_CONVERTED
    assert runs_for_rows(user.library, [row.pk]) == {}


@pytest.mark.django_db(transaction=True)
def test_an_event_naming_a_run_this_library_cannot_read_says_so(
    user, game, capture_games_logger
):
    """Drift, not an untracked game.

    The event is pointed at an id no row carries, which is
    what a lagging projection or a rebuild mid-swap looks
    like from here. Nothing destroys a projection row, so
    that is the only way to reach this state.
    """
    row = PlayEvent.objects.create(game=game, started=None, ended=None, note="")
    convert_library(user.library)
    LibraryEvent.objects.filter(
        library=user.library,
        event_type=PLAYTHROUGH_CREATED.event_type,
        source_metadata__play_event_id=str(row.pk),
    ).update(aggregate_id=uuid.uuid7())

    with capture_games_logger() as caplog:
        converted = run_for_row(user.library, row.pk)

    assert converted.run is None
    assert not converted.never_converted
    assert converted.sentence == RUN_UNREADABLE
    assert "converted playthrough unreadable" in caplog.text


@pytest.mark.django_db(transaction=True)
def test_a_default_run_maps_to_no_row(user, game):
    convert_library(user.library)

    assert runs_for_rows(user.library, [game.pk]) == {}
