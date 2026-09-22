"""Retracting the record of an endpoint."""

from datetime import date

import pytest

from games.commands.playergame import TrackGame
from games.commands.playthrough import (
    CompletePlaythrough,
    StartPlaythrough,
    VoidPlaythroughCompletion,
    VoidPlaythroughStart,
)
from games.events.dispatch import CommandOutcome, CommandRejected, dispatch
from games.models import Game, LibraryEvent, PlayerGame, Playthrough
from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.untracked_games

DAY = TemporalValue.from_day(date(2026, 3, 4))
OTHER_DAY = TemporalValue.from_day(date(2026, 5, 6))


@pytest.fixture
def game(owned_library):
    return Game.objects.create(library=owned_library, name="Outer Wilds")


@pytest.fixture
def run(owned_user, owned_library, game):
    """The run a tracked game holds."""
    dispatch(
        TrackGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="track",
    )
    return Playthrough.objects.get()


def _state(command, owned_user, owned_library, key):
    return dispatch(
        command, actor=owned_user, library=owned_library, idempotency_key=key
    )


def _start(run, owned_user, owned_library, when=DAY, note=""):
    _state(
        StartPlaythrough(playthrough_id=run.pk, when=when, note=note),
        owned_user,
        owned_library,
        "start",
    )


def _complete(run, owned_user, owned_library, when=DAY, note=""):
    _state(
        CompletePlaythrough(playthrough_id=run.pk, when=when, note=note),
        owned_user,
        owned_library,
        "complete",
    )


@pytest.mark.django_db(transaction=True)
def test_a_stated_start_is_voided(owned_user, owned_library, run):
    _start(run, owned_user, owned_library, note="from the box")

    result = _state(
        VoidPlaythroughStart(playthrough_id=run.pk), owned_user, owned_library, "void"
    )

    assert result.outcome is CommandOutcome.APPENDED
    run.refresh_from_db()
    assert run.started is None
    assert run.start_recorded_at is None
    assert run.start_note == ""


@pytest.mark.django_db(transaction=True)
def test_a_voided_start_leaves_the_completion(owned_user, owned_library, run):
    _start(run, owned_user, owned_library)
    _complete(run, owned_user, owned_library, when=OTHER_DAY, note="all endings")

    _state(
        VoidPlaythroughStart(playthrough_id=run.pk), owned_user, owned_library, "void"
    )

    run.refresh_from_db()
    assert run.completed == OTHER_DAY
    assert run.completion_recorded_at is not None
    assert run.completion_note == "all endings"


@pytest.mark.django_db(transaction=True)
def test_an_unstated_start_is_unchanged(owned_user, owned_library, run):
    result = _state(
        VoidPlaythroughStart(playthrough_id=run.pk), owned_user, owned_library, "void"
    )

    assert result.outcome is CommandOutcome.UNCHANGED
    assert not LibraryEvent.objects.filter(
        aggregate_id=run.pk, event_type="library.playthrough.start_voided"
    ).exists()


@pytest.mark.django_db(transaction=True)
def test_a_removed_run_refuses_the_void(owned_user, owned_library, run):
    _start(run, owned_user, owned_library)
    Playthrough.objects.filter(pk=run.pk).update(removed_at=run.created_at)

    with pytest.raises(CommandRejected) as refusal:
        _state(
            VoidPlaythroughStart(playthrough_id=run.pk),
            owned_user,
            owned_library,
            "void",
        )

    assert refusal.value.sentence
    run.refresh_from_db()
    assert run.started == DAY


@pytest.mark.django_db(transaction=True)
def test_a_removed_game_refuses_the_void(owned_user, owned_library, run):
    _start(run, owned_user, owned_library)
    tracked = PlayerGame.objects.get()
    PlayerGame.objects.filter(pk=tracked.pk).update(removed_at=tracked.tracked_at)

    with pytest.raises(CommandRejected) as refusal:
        _state(
            VoidPlaythroughStart(playthrough_id=run.pk),
            owned_user,
            owned_library,
            "void",
        )

    assert refusal.value.sentence == (
        "That game was removed from your library. Restore it before "
        "changing its playthroughs."
    )


@pytest.mark.django_db(transaction=True)
def test_an_unstated_start_under_a_removed_game_is_unchanged(
    owned_user, owned_library, run
):
    """The no-op answers before the refusal."""
    tracked = PlayerGame.objects.get()
    PlayerGame.objects.filter(pk=tracked.pk).update(removed_at=tracked.tracked_at)

    result = _state(
        VoidPlaythroughStart(playthrough_id=run.pk), owned_user, owned_library, "void"
    )

    assert result.outcome is CommandOutcome.UNCHANGED


@pytest.mark.django_db(transaction=True)
def test_a_stated_completion_is_voided(owned_user, owned_library, run):
    _start(run, owned_user, owned_library)
    _complete(run, owned_user, owned_library, when=OTHER_DAY, note="all endings")

    _state(
        VoidPlaythroughCompletion(playthrough_id=run.pk),
        owned_user,
        owned_library,
        "void",
    )

    run.refresh_from_db()
    assert run.completed is None
    assert run.completion_recorded_at is None
    assert run.completion_note == ""
    assert run.started == DAY


@pytest.mark.django_db(transaction=True)
def test_an_unstated_completion_is_unchanged(owned_user, owned_library, run):
    result = _state(
        VoidPlaythroughCompletion(playthrough_id=run.pk),
        owned_user,
        owned_library,
        "void",
    )

    assert result.outcome is CommandOutcome.UNCHANGED
