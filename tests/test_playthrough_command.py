"""Dispatching the command that states a run at a game."""

import pytest

from games.commands.playergame import PlayerGameNotTracked, TrackGame
from games.commands.playthrough import CreatePlaythrough
from games.events.dispatch import CommandOutcome, CommandRejected, dispatch
from games.models import Game, LibraryEvent, PlayerGame, Playthrough

pytestmark = pytest.mark.untracked_games


@pytest.fixture
def game(owned_library):
    return Game.objects.create(library=owned_library, name="Outer Wilds")


def _track(owned_user, owned_library, game, key="track"):
    return dispatch(
        TrackGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key=key,
    )


@pytest.mark.django_db(transaction=True)
def test_creating_a_playthrough_records_it_and_projects_it(
    owned_user, owned_library, game
):
    _track(owned_user, owned_library, game)

    result = dispatch(
        CreatePlaythrough(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="second-run",
    )

    assert result.outcome is CommandOutcome.APPENDED
    events = LibraryEvent.objects.filter(
        event_type="library.playthrough.created"
    ).order_by("sequence")
    assert events.count() == 2
    tracked = PlayerGame.objects.get()
    assert events.last().payload == {
        "player_game": str(tracked.pk),
        "kind": "ordinary",
    }
    assert Playthrough.objects.filter(player_game=tracked).count() == 2


@pytest.mark.django_db(transaction=True)
def test_creating_a_playthrough_for_an_untracked_game_is_refused(
    owned_user, owned_library, game
):
    with pytest.raises(PlayerGameNotTracked):
        dispatch(
            CreatePlaythrough(game_id=game.pk),
            actor=owned_user,
            library=owned_library,
            idempotency_key="untracked",
        )

    assert Playthrough.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_creating_a_playthrough_for_a_removed_game_is_refused(
    owned_user, owned_library, game
):
    _track(owned_user, owned_library, game)
    tracked = PlayerGame.objects.get()
    PlayerGame.objects.filter(pk=tracked.pk).update(removed_at=tracked.tracked_at)

    with pytest.raises(CommandRejected) as refusal:
        dispatch(
            CreatePlaythrough(game_id=game.pk),
            actor=owned_user,
            library=owned_library,
            idempotency_key="removed",
        )

    assert "Restore it" in refusal.value.sentence
    #: Only the default, from TrackGame.
    assert Playthrough.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_a_repeat_under_one_key_records_nothing_further(
    owned_user, owned_library, game
):
    _track(owned_user, owned_library, game)
    for _ in range(2):
        dispatch(
            CreatePlaythrough(game_id=game.pk),
            actor=owned_user,
            library=owned_library,
            idempotency_key="second-run",
        )

    assert Playthrough.objects.count() == 2
