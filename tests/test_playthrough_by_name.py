"""The run a person names from a picker.

The create row states a name and nothing else. The command
decides whether that names the run tracking minted or makes
one more, and it decides under the stream head's lock.
"""

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone
from stated_runs import another_run, state_run

from games.commands.historical_playtime import (
    HistoricalPlaytimeStatement,
    RecordHistoricalPlaytime,
)
from games.commands.playergame import TrackGame
from games.commands.playersession import CreateSession, TimedTiming
from games.commands.playthrough import (
    PLAYTHROUGH_NAME_MAX_LENGTH,
    ActStatement,
    RecordPlaythroughByName,
)
from games.events.dispatch import CommandOutcome, CommandRejected, dispatch
from games.models import (
    Game,
    HistoricalPlaytimeProvenance,
    PlayerGame,
    Playthrough,
    PlaythroughKind,
)
from games.reads.playthrough_runs import live_ordinary_runs, tracked_game
from games.writes.playergame import new_correlation_id
from games.writes.playthrough import record_named_run

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.untracked_games]


@pytest.fixture
def game(owned_library):
    return Game.objects.create(library=owned_library, name="Outer Wilds")


def _track(user, game: Game) -> None:
    dispatch(
        TrackGame(game_id=game.pk),
        actor=user,
        library=user.library,
        idempotency_key=str(uuid.uuid7()),
    )


def _born_run(user, game: Game) -> Playthrough:
    player_game = tracked_game(user.library, game)
    assert player_game is not None
    return live_ordinary_runs(user.library, player_game).get()


def _ordinary_runs(user, game: Game):
    return Playthrough.objects.filter(
        library=user.library,
        player_game__game=game,
        removed_at__isnull=True,
        kind=PlaythroughKind.ORDINARY,
    )


def _name(user, game: Game, name: str = "New Game Plus"):
    return record_named_run(user, game, name, correlation_id=new_correlation_id())


def _state(user, game: Game, name: str):
    """The command itself: the write path answers a refusal."""
    return dispatch(
        RecordPlaythroughByName(game_id=game.pk, name=name),
        actor=user,
        library=user.library,
        idempotency_key=str(uuid.uuid7()),
    )


def _session_on(user, run: Playthrough) -> None:
    dispatch(
        CreateSession(
            playthrough_id=run.pk,
            timing=TimedTiming(
                started_at=timezone.now() - timedelta(hours=1), day_zone="UTC"
            ),
        ),
        actor=user,
        library=user.library,
        idempotency_key=str(uuid.uuid7()),
    )


def _record_on(user, run: Playthrough) -> None:
    dispatch(
        RecordHistoricalPlaytime(
            statement=HistoricalPlaytimeStatement(
                duration=timedelta(hours=10),
                when="2005",
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


def test_a_placeholder_is_adopted_and_named(owned_user, game):
    _track(owned_user, game)
    placeholder = _born_run(owned_user, game)

    named = _name(owned_user, game)

    assert named.playthrough_id == placeholder.pk
    assert named.tracked_the_game is False
    placeholder.refresh_from_db()
    assert placeholder.name == "New Game Plus"
    assert _ordinary_runs(owned_user, game).count() == 1


def test_a_run_holding_a_session_is_not_adopted(owned_user, game):
    _track(owned_user, game)
    placeholder = _born_run(owned_user, game)
    _session_on(owned_user, placeholder)

    named = _name(owned_user, game)

    assert named.playthrough_id != placeholder.pk
    assert _ordinary_runs(owned_user, game).count() == 2


def test_a_run_holding_a_record_is_not_adopted(owned_user, game):
    _track(owned_user, game)
    placeholder = _born_run(owned_user, game)
    _record_on(owned_user, placeholder)

    named = _name(owned_user, game)

    assert named.playthrough_id != placeholder.pk
    assert _ordinary_runs(owned_user, game).count() == 2


def test_a_named_run_is_not_adopted(owned_user, game):
    _track(owned_user, game)
    placeholder = _born_run(owned_user, game)
    Playthrough.objects.filter(pk=placeholder.pk).update(name="Main")

    named = _name(owned_user, game)

    assert named.playthrough_id != placeholder.pk
    assert _ordinary_runs(owned_user, game).count() == 2


def test_a_started_run_is_not_adopted(owned_user, game):
    _track(owned_user, game)
    started = state_run(owned_user, game, started=ActStatement(None))

    named = _name(owned_user, game)

    assert named.playthrough_id != started.pk
    assert _ordinary_runs(owned_user, game).count() == 2


def test_two_runs_adopt_neither(owned_user, game):
    _track(owned_user, game)
    held = set(_ordinary_runs(owned_user, game).values_list("pk", flat=True))
    another_run(owned_user, game)

    named = _name(owned_user, game)

    assert named.playthrough_id not in held
    assert _ordinary_runs(owned_user, game).count() == 3


def test_an_untracked_game_ends_with_one_named_run(owned_user, game):
    named = _name(owned_user, game)

    assert named.tracked_the_game is True
    runs = list(_ordinary_runs(owned_user, game))
    assert [run.pk for run in runs] == [named.playthrough_id]
    assert runs[0].name == "New Game Plus"


def test_a_blank_name_is_refused(owned_user, game):
    _track(owned_user, game)

    with pytest.raises(CommandRejected) as refusal:
        _state(owned_user, game, "   ")

    assert refusal.value.sentence


def test_a_name_the_column_cannot_hold_is_refused(owned_user, game):
    _track(owned_user, game)

    with pytest.raises(CommandRejected) as refusal:
        _state(owned_user, game, "x" * (PLAYTHROUGH_NAME_MAX_LENGTH + 1))

    assert "too long" in refusal.value.sentence


def test_a_removed_game_is_refused(owned_user, game):
    """The projection's mark, which is the one the build reads."""
    _track(owned_user, game)
    PlayerGame.objects.filter(library=owned_user.library, game=game).update(
        removed_at=timezone.now()
    )

    with pytest.raises(CommandRejected) as refusal:
        _state(owned_user, game, "New Game Plus")

    assert refusal.value.sentence


def test_the_same_name_twice_answers_unchanged(owned_user, owned_library, game):
    _track(owned_user, game)
    placeholder = _born_run(owned_user, game)

    _name(owned_user, game)
    result = dispatch(
        RecordPlaythroughByName(game_id=game.pk, name="New Game Plus"),
        actor=owned_user,
        library=owned_library,
        idempotency_key=str(uuid.uuid7()),
    )

    assert result.outcome is CommandOutcome.UNCHANGED
    assert _ordinary_runs(owned_user, game).count() == 1
    placeholder.refresh_from_db()
    assert placeholder.name == "New Game Plus"
