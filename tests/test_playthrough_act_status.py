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
from games.reads.events import dispatched_events
from games.writes.answers import CommandFailed
from games.writes.playergame import new_correlation_id, record_facts
from games.writes.playthrough import complete_run, start_run
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


def _start(owned_user, run, *, implies_status=True, key=None, when=DAY):
    return start_run(
        owned_user,
        run,
        when,
        implies_status=implies_status,
        correlation_id=new_correlation_id(),
        idempotency_key=key,
    )


@pytest.mark.django_db(transaction=True)
def test_a_start_states_played_last_in_its_own_dispatch(owned_user, run, game):
    result = _start(owned_user, run)

    assert result.outcome is CommandOutcome.APPENDED
    types = list(dispatched_events(result).values_list("event_type", flat=True))
    assert types == ["library.playthrough.started", STATUS_CHANGED]
    assert PlayerGame.objects.get().status == PlayerGameStatus.PLAYED


@pytest.mark.django_db(transaction=True)
def test_a_start_without_the_box_states_no_status(owned_user, run, game):
    _start(owned_user, run, implies_status=False)

    assert PlayerGame.objects.get().status == PlayerGameStatus.UNPLAYED


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "held",
    [
        PlayerGameStatus.PLAYED,
        PlayerGameStatus.COMPLETED,
        PlayerGameStatus.RETIRED,
        PlayerGameStatus.SHELVED,
        PlayerGameStatus.ABANDONED,
    ],
)
def test_a_start_never_walks_a_status_back(owned_user, run, game, held):
    record_facts(owned_user, game, status=held, correlation_id=new_correlation_id())

    result = _start(owned_user, run)

    assert result.outcome is CommandOutcome.APPENDED
    assert PlayerGame.objects.get().status == held
    assert _status_events(game).count() == 1


@pytest.mark.django_db(transaction=True)
def test_a_completion_states_completed(owned_user, run, game):
    complete_run(
        owned_user,
        run,
        DAY,
        implies_status=True,
        correlation_id=new_correlation_id(),
    )

    assert PlayerGame.objects.get().status == PlayerGameStatus.COMPLETED


@pytest.mark.django_db(transaction=True)
def test_a_completion_completes_over_abandoned(owned_user, run, game):
    record_facts(
        owned_user,
        game,
        status=PlayerGameStatus.ABANDONED,
        correlation_id=new_correlation_id(),
    )

    complete_run(
        owned_user,
        run,
        DAY,
        implies_status=True,
        correlation_id=new_correlation_id(),
    )

    assert PlayerGame.objects.get().status == PlayerGameStatus.COMPLETED


@pytest.mark.django_db(transaction=True)
def test_an_unchanged_endpoint_states_no_status(owned_user, run, game):
    """A run already stating that day implies nothing."""
    _start(owned_user, run)
    record_facts(
        owned_user,
        game,
        status=PlayerGameStatus.UNPLAYED,
        correlation_id=new_correlation_id(),
    )

    result = _start(owned_user, run)

    assert result.outcome is CommandOutcome.UNCHANGED
    assert PlayerGame.objects.get().status == PlayerGameStatus.UNPLAYED


@pytest.mark.django_db(transaction=True)
def test_a_replayed_act_states_nothing_new(owned_user, run, game):
    first = _start(owned_user, run, key="one-row")
    again = _start(owned_user, run, key="one-row")

    assert (first.outcome, again.outcome) == (
        CommandOutcome.APPENDED,
        CommandOutcome.REPLAYED,
    )
    assert _status_events(game).count() == 1


@pytest.mark.django_db(transaction=True)
def test_a_refused_endpoint_rises(owned_user, run, game):
    _start(owned_user, run)

    with pytest.raises(CommandFailed):
        _start(owned_user, run, when=OTHER_DAY)
