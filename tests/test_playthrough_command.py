"""Dispatching the commands that state a run."""

import pytest

from games.commands.playergame import PlayerGameNotTracked, TrackGame
from games.commands.playthrough import CreatePlaythrough
from games.events.dispatch import CommandOutcome, CommandRejected, dispatch
from games.models import (
    Game,
    LibraryEvent,
    PlayerGame,
    Playthrough,
    PlaythroughKind,
)

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


@pytest.mark.django_db(transaction=True)
def test_tracking_a_game_states_its_first_playthrough(owned_user, owned_library, game):
    """The first act states both facts."""
    _track(owned_user, owned_library, game)

    events = list(LibraryEvent.objects.order_by("sequence"))
    assert [event.event_type for event in events] == [
        "library.playergame.created",
        "library.playthrough.created",
    ]
    #: One dispatch, one correlation_id.
    assert len({event.correlation_id for event in events}) == 1
    assert events[1].sequence == events[0].sequence + 1

    tracked = PlayerGame.objects.get()
    run = Playthrough.objects.get()
    assert events[1].payload == {
        "player_game": str(tracked.pk),
        "kind": "ordinary",
    }
    assert (run.player_game_id, run.kind, run.library_id) == (
        tracked.pk,
        PlaythroughKind.ORDINARY,
        owned_library.pk,
    )


@pytest.mark.django_db(transaction=True)
def test_a_repeated_track_under_one_key_states_one_playthrough(
    owned_user, owned_library, game
):
    """A repeat answers from the idempotency record."""
    _track(owned_user, owned_library, game)
    _track(owned_user, owned_library, game)

    assert Playthrough.objects.count() == 1
    assert LibraryEvent.objects.count() == 2


@pytest.mark.django_db(transaction=True)
def test_tracking_an_already_tracked_game_states_no_second_default(
    owned_user, owned_library, game
):
    """#684 supplies a missing default, not TrackGame."""
    _track(owned_user, owned_library, game, key="first")
    result = _track(owned_user, owned_library, game, key="second")

    assert result.outcome is CommandOutcome.UNCHANGED
    assert Playthrough.objects.count() == 1
