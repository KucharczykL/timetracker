"""One endpoint, and the status the act implies."""

from datetime import date

import pytest

from games.commands.playergame import TrackGame
from games.events.dispatch import CommandOutcome, dispatch
from games.models import (
    Game,
    LibraryEvent,
    PlayerGame,
    PlayerGameStatus,
    Playthrough,
)
from games.writes.answers import CommandFailed
from games.writes.playergame import new_correlation_id, record_facts
from games.writes.playthrough_endpoints import state_completion, state_start
from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.untracked_games

DAY = TemporalValue.from_day(date(2026, 3, 4))
OTHER_DAY = TemporalValue.from_day(date(2026, 5, 6))

STATUS_CHANGED = "library.playergame.status_changed"


@pytest.fixture
def game(owned_library):
    return Game.objects.create(library=owned_library, name="Outer Wilds")


@pytest.fixture
def run(owned_user, owned_library, game):
    dispatch(
        TrackGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="track",
    )
    return Playthrough.objects.get()


def _status_events(game):
    tracked = PlayerGame.objects.get(game=game)
    return LibraryEvent.objects.filter(
        aggregate_id=tracked.pk, event_type=STATUS_CHANGED
    )


@pytest.mark.django_db(transaction=True)
def test_a_start_states_played_on_an_unplayed_game(owned_user, run, game):
    correlation_id = new_correlation_id()

    stated = state_start(owned_user, run, DAY, correlation_id=correlation_id)

    assert stated.result.outcome is CommandOutcome.APPENDED
    assert stated.status_refusal is None
    assert PlayerGame.objects.get().status == PlayerGameStatus.PLAYED
    assert _status_events(game).get().correlation_id == correlation_id


@pytest.mark.django_db(transaction=True)
def test_a_start_leaves_a_stronger_status(owned_user, run, game):
    record_facts(
        owned_user,
        game,
        status=PlayerGameStatus.COMPLETED,
        correlation_id=new_correlation_id(),
    )

    state_start(owned_user, run, DAY, correlation_id=new_correlation_id())

    assert PlayerGame.objects.get().status == PlayerGameStatus.COMPLETED
    assert _status_events(game).count() == 1


@pytest.mark.django_db(transaction=True)
def test_a_completion_states_completed(owned_user, run, game):
    state_completion(owned_user, run, DAY, correlation_id=new_correlation_id())

    assert PlayerGame.objects.get().status == PlayerGameStatus.COMPLETED


@pytest.mark.django_db(transaction=True)
def test_an_unchanged_endpoint_states_no_status(owned_user, run, game):
    """A run that already states that day implies nothing."""
    state_start(owned_user, run, DAY, correlation_id=new_correlation_id())
    record_facts(
        owned_user,
        game,
        status=PlayerGameStatus.UNPLAYED,
        correlation_id=new_correlation_id(),
    )

    stated = state_start(
        owned_user, run, DAY, correlation_id=new_correlation_id(), idempotency_key=None
    )

    assert stated.result.outcome is CommandOutcome.UNCHANGED
    assert PlayerGame.objects.get().status == PlayerGameStatus.UNPLAYED


@pytest.mark.django_db(transaction=True)
def test_a_replayed_endpoint_states_the_status(owned_user, run, game):
    """The second post finishes what the first never reached."""
    for _ in range(2):
        stated = state_start(
            owned_user,
            run,
            DAY,
            correlation_id=new_correlation_id(),
            idempotency_key="one-row",
        )

    assert stated.result.outcome is CommandOutcome.REPLAYED
    assert PlayerGame.objects.get().status == PlayerGameStatus.PLAYED


@pytest.mark.django_db(transaction=True)
def test_the_status_key_is_derived_from_the_row_key(owned_user, run, game):
    for _ in range(2):
        state_start(
            owned_user,
            run,
            DAY,
            correlation_id=new_correlation_id(),
            idempotency_key="one-row",
        )

    assert _status_events(game).count() == 1


@pytest.mark.django_db(transaction=True)
def test_a_refused_endpoint_rises(owned_user, run, game):
    state_start(owned_user, run, DAY, correlation_id=new_correlation_id())

    with pytest.raises(CommandFailed):
        state_start(owned_user, run, OTHER_DAY, correlation_id=new_correlation_id())


@pytest.mark.django_db(transaction=True)
def test_a_refused_status_is_carried_back(owned_user, run, game, monkeypatch):
    """The endpoint stands; the row is not refused for the status."""
    refusal = CommandFailed("That game was removed from your library.", 409)

    def refuse(*arguments, **facts):
        raise refusal

    monkeypatch.setattr(
        "games.writes.playthrough_endpoints.record_facts",
        refuse,
    )

    stated = state_completion(owned_user, run, DAY, correlation_id=new_correlation_id())

    assert stated.result.outcome is CommandOutcome.APPENDED
    assert stated.status_refusal is refusal
    run.refresh_from_db()
    assert run.completed == DAY


@pytest.mark.django_db(transaction=True)
def test_a_status_defect_ends_the_act(owned_user, run, game, monkeypatch):
    """Anything but a conflict is the batch's to end on."""

    def fail(*arguments, **facts):
        raise CommandFailed("The database refused the statement.", 500)

    monkeypatch.setattr("games.writes.playthrough_endpoints.record_facts", fail)

    with pytest.raises(CommandFailed):
        state_completion(owned_user, run, DAY, correlation_id=new_correlation_id())
