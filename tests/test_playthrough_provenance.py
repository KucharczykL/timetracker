"""The run a converted legacy row became, read from its provenance."""

import pytest

from games.backfill.playthrough import convert_library
from games.models import Game, PlayEvent
from games.reads.playthrough_provenance import run_for_row, runs_for_rows


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

    run = run_for_row(user.library, row.pk)

    assert run is not None
    assert run.player_game.game_id == game.pk


@pytest.mark.django_db(transaction=True)
def test_a_row_the_conversion_never_saw_maps_to_nothing(user, game):
    row = PlayEvent.objects.create(game=game, started=None, ended=None, note="")

    assert run_for_row(user.library, row.pk) is None
    assert runs_for_rows(user.library, [row.pk]) == {}


@pytest.mark.django_db(transaction=True)
def test_a_default_run_maps_to_no_row(user, game):
    convert_library(user.library)

    assert runs_for_rows(user.library, [game.pk]) == {}
