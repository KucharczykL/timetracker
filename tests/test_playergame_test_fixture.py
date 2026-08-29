"""The autouse fixture that tracks a created game."""

import pytest

from games.models import Game, PlayerGame, PlayerGameStatus


@pytest.mark.django_db
def test_a_created_game_is_tracked(owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")

    row = PlayerGame.objects.get(library=owned_library, game=game)
    assert row.status == PlayerGameStatus.UNPLAYED
    assert row.tracked_at is not None


@pytest.mark.django_db
def test_a_shared_game_is_tracked_by_nobody():
    game = Game.objects.create(library=None, name="Shared")

    assert not PlayerGame.objects.filter(game=game).exists()


@pytest.mark.django_db
@pytest.mark.untracked_games
def test_the_marker_suppresses_the_row(owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")

    assert not PlayerGame.objects.filter(game=game).exists()
