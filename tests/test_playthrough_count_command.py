"""Stating how many times a game was played through."""

import uuid
from datetime import date
from typing import NamedTuple

import pytest
from django.utils import timezone
from historical_playtime_rows import record_row
from session_rows import timed_row

from games.commands import playthrough_count
from games.commands.playergame import RecordPlayerGameFacts
from games.commands.playthrough import (
    CompletePlaythrough,
    CorrectPlaythroughCompletion,
    CreatePlaythrough,
    DescribePlaythrough,
)
from games.commands.playthrough_count import (
    CHANGED_SINCE,
    StatePlaythroughCount,
    UndoPlaythroughCount,
    count_statement_key,
)
from games.events.dispatch import (
    CommandOutcome,
    CommandRejected,
    CommandResult,
    RowNotHeld,
    RowUnreadable,
    dispatch,
)
from games.models import Game, PlayerGame, PlayerGameStatus, Playthrough
from games.reads.playthrough_count import dateless_runs
from games.reads.playthrough_runs import completed_run_count, live_ordinary_runs
from games.writes.playergame import new_correlation_id, track_game
from games.writes.playthrough_count import undo_times_played
from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.untracked_games

DAY = TemporalValue.from_day(date(2020, 1, 2))


@pytest.fixture
def game(owned_library):
    return Game.objects.create(library=owned_library, name="Outer Wilds")


@pytest.fixture
def tracked(owned_user, game) -> PlayerGame:
    track_game(owned_user, game, correlation_id=new_correlation_id())
    return PlayerGame.objects.get(game=game)


def _run(owned_user, command, *, correlation_id=None, key=None):
    return dispatch(
        command,
        actor=owned_user,
        library=owned_user.library,
        idempotency_key=key or str(uuid.uuid7()),
        correlation_id=correlation_id,
    )


class Statement(NamedTuple):
    """One count statement and its correlation."""

    correlation: uuid.UUID
    stated: int
    result: CommandResult | None = None


def _state(owned_user, game, count) -> Statement:
    correlation = uuid.uuid7()
    result = _run(
        owned_user,
        StatePlaythroughCount(game_id=game.pk, count=count),
        correlation_id=correlation,
        key=count_statement_key(correlation),
    )
    return Statement(correlation, count, result)


def _undo(owned_user, game, statement: Statement, *, key=None):
    return _run(
        owned_user,
        UndoPlaythroughCount(
            game_id=game.pk,
            statement_id=statement.correlation,
            stated=statement.stated,
        ),
        key=key,
    )


def _total(owned_library, tracked) -> int:
    return completed_run_count(owned_library, tracked)


def _live(owned_library, tracked) -> list[Playthrough]:
    return list(live_ordinary_runs(owned_library, tracked))


def _status(tracked) -> str:
    tracked.refresh_from_db()
    return tracked.status


def _dated_run(owned_user, game) -> None:
    _run(
        owned_user,
        CreatePlaythrough(
            game_id=game.pk,
            started=None,
            completed=None,
            implies_played=False,
            implies_completed=False,
        ),
    )
    run = Playthrough.objects.filter(player_game__game=game).latest("created_at")
    _run(
        owned_user,
        CompletePlaythrough(
            playthrough_id=run.pk, when=DAY, note="", implies_status=False
        ),
    )


# State


@pytest.mark.django_db(transaction=True)
def test_a_raise_fills_the_bare_run_then_creates_the_rest(
    owned_user, owned_library, game, tracked
):
    bare = _live(owned_library, tracked)[0]

    _state(owned_user, game, 3)

    runs = _live(owned_library, tracked)
    assert len(runs) == 3
    assert runs[0] == bare
    assert all(
        run.start_recorded_at and run.completion_recorded_at and run.started is None
        for run in runs
    )
    assert _total(owned_library, tracked) == 3


@pytest.mark.django_db(transaction=True)
def test_a_raise_states_completed(owned_user, owned_library, game, tracked):
    _state(owned_user, game, 1)

    assert _status(tracked) == PlayerGameStatus.COMPLETED


@pytest.mark.django_db(transaction=True)
def test_a_raise_beside_a_dated_run_adds_the_difference(
    owned_user, owned_library, game, tracked
):
    Playthrough.objects.filter(player_game=tracked).update(name="First")
    _dated_run(owned_user, game)

    _state(owned_user, game, 3)

    assert _total(owned_library, tracked) == 3
    assert len(_live(owned_library, tracked)) == 4


@pytest.mark.django_db(transaction=True)
def test_a_noted_sole_run_is_not_filled(owned_user, owned_library, game, tracked):
    run = _live(owned_library, tracked)[0]
    _run(
        owned_user, DescribePlaythrough(playthrough_id=run.pk, name=None, note="Saved")
    )

    _state(owned_user, game, 1)

    run.refresh_from_db()
    assert run.completion_recorded_at is None
    assert len(_live(owned_library, tracked)) == 2


@pytest.mark.django_db(transaction=True)
def test_a_lower_removes_the_newest_dateless_runs(
    owned_user, owned_library, game, tracked
):
    _state(owned_user, game, 4)
    kept = _live(owned_library, tracked)[:2]

    _state(owned_user, game, 2)

    assert _live(owned_library, tracked) == kept
    assert _total(owned_library, tracked) == 2


@pytest.mark.django_db(transaction=True)
def test_a_lower_states_no_status(owned_user, owned_library, game, tracked):
    _state(owned_user, game, 2)
    _run(
        owned_user,
        RecordPlayerGameFacts(game_id=game.pk, status=PlayerGameStatus.PLAYED),
    )

    _state(owned_user, game, 1)

    assert _status(tracked) == PlayerGameStatus.PLAYED


@pytest.mark.django_db(transaction=True)
def test_a_lower_to_zero_keeps_one_bare_run(owned_user, owned_library, game, tracked):
    _state(owned_user, game, 3)
    oldest = _live(owned_library, tracked)[0]

    _state(owned_user, game, 0)

    runs = _live(owned_library, tracked)
    assert runs == [oldest]
    assert runs[0].start_recorded_at is None
    assert runs[0].completion_recorded_at is None


@pytest.mark.django_db(transaction=True)
def test_a_lower_to_zero_beside_an_unfinished_run_removes_every_count_run(
    owned_user, owned_library, game, tracked
):
    Playthrough.objects.filter(player_game=tracked).update(name="Ongoing")
    _state(owned_user, game, 2)

    _state(owned_user, game, 0)

    assert [run.name for run in _live(owned_library, tracked)] == ["Ongoing"]


@pytest.mark.django_db(transaction=True)
def test_a_lower_past_the_dateless_runs_is_refused_whole(
    owned_user, owned_library, game, tracked
):
    Playthrough.objects.filter(player_game=tracked).update(name="First")
    _dated_run(owned_user, game)
    _state(owned_user, game, 2)

    with pytest.raises(CommandRejected) as refused:
        _state(owned_user, game, 0)

    assert "Only 1" in refused.value.sentence
    assert _total(owned_library, tracked) == 2


@pytest.mark.django_db(transaction=True)
def test_a_dateless_run_a_removed_session_names_is_kept(
    owned_user, owned_library, game, tracked
):
    _state(owned_user, game, 2)
    newest = _live(owned_library, tracked)[-1]
    session = timed_row(newest, timezone.now(), None)
    type(session).objects.filter(pk=session.pk).update(removed_at=timezone.now())

    _state(owned_user, game, 1)

    assert newest in _live(owned_library, tracked)
    assert _total(owned_library, tracked) == 1


@pytest.mark.django_db(transaction=True)
def test_the_stated_total_is_unchanged(owned_user, owned_library, game, tracked):
    _state(owned_user, game, 2)

    again = _state(owned_user, game, 2)

    assert again.result is not None
    assert again.result.outcome is CommandOutcome.UNCHANGED


@pytest.mark.django_db(transaction=True)
def test_a_raise_above_the_bound_is_refused(owned_user, game, tracked):
    with pytest.raises(CommandRejected) as refused:
        _state(owned_user, game, 101)

    assert refused.value.sentence == "State 100 times or fewer."


@pytest.mark.django_db(transaction=True)
def test_a_raise_to_the_bound_is_allowed(
    owned_user, owned_library, game, tracked, monkeypatch
):
    monkeypatch.setattr(playthrough_count, "MAX_TIMES_PLAYED", 2)

    _state(owned_user, game, 2)

    assert _total(owned_library, tracked) == 2


@pytest.mark.django_db(transaction=True)
def test_a_lower_above_the_bound_is_allowed(
    owned_user, owned_library, game, tracked, monkeypatch
):
    stamp = timezone.now()
    for _ in range(4):
        Playthrough.objects.create(
            id=uuid.uuid7(),
            library=owned_library,
            player_game=tracked,
            kind="ordinary",
            created_at=stamp,
            start_recorded_at=stamp,
            completion_recorded_at=stamp,
        )
    monkeypatch.setattr(playthrough_count, "MAX_TIMES_PLAYED", 2)

    _state(owned_user, game, 3)

    assert _total(owned_library, tracked) == 3


@pytest.mark.django_db(transaction=True)
def test_a_negative_count_is_refused(owned_user, game, tracked):
    with pytest.raises(CommandRejected) as refused:
        _state(owned_user, game, -1)

    assert refused.value.sentence == "Times played cannot be below zero."


@pytest.mark.django_db(transaction=True)
def test_an_untracked_game_is_refused(owned_user, game):
    with pytest.raises(CommandRejected) as refused:
        _state(owned_user, game, 1)

    assert "not in your library" in refused.value.sentence


@pytest.mark.django_db(transaction=True)
def test_a_removed_game_is_refused(owned_user, game, tracked):
    PlayerGame.objects.filter(pk=tracked.pk).update(removed_at=timezone.now())

    with pytest.raises(CommandRejected) as refused:
        _state(owned_user, game, 1)

    assert "removed" in refused.value.sentence


# Undo


@pytest.mark.django_db(transaction=True)
def test_undo_of_a_raise_restores_the_bare_run_and_status(
    owned_user, owned_library, game, tracked
):
    bare = _live(owned_library, tracked)[0]
    statement = _state(owned_user, game, 3)

    _undo(owned_user, game, statement)

    runs = _live(owned_library, tracked)
    assert runs == [bare]
    assert runs[0].completion_recorded_at is None
    assert _status(tracked) == PlayerGameStatus.UNPLAYED


@pytest.mark.django_db(transaction=True)
def test_undo_of_a_lower_restores_the_same_runs(
    owned_user, owned_library, game, tracked
):
    _state(owned_user, game, 3)
    before = _live(owned_library, tracked)
    statement = _state(owned_user, game, 0)

    _undo(owned_user, game, statement)

    assert _live(owned_library, tracked) == before
    assert _total(owned_library, tracked) == 3


@pytest.mark.django_db(transaction=True)
def test_undo_is_refused_after_a_run_was_dated(
    owned_user, owned_library, game, tracked
):
    statement = _state(owned_user, game, 2)
    run = _live(owned_library, tracked)[-1]
    _run(
        owned_user,
        CorrectPlaythroughCompletion(playthrough_id=run.pk, when=DAY, note=""),
    )

    with pytest.raises(CommandRejected) as refused:
        _undo(owned_user, game, statement)

    assert refused.value.sentence == CHANGED_SINCE
    assert "states an event after" in str(refused.value)
    assert _total(owned_library, tracked) == 2


@pytest.mark.django_db(transaction=True)
def test_undo_is_refused_after_a_run_was_named(
    owned_user, owned_library, game, tracked
):
    statement = _state(owned_user, game, 2)
    run = _live(owned_library, tracked)[-1]
    _run(owned_user, DescribePlaythrough(playthrough_id=run.pk, name="Hard", note=None))

    with pytest.raises(CommandRejected) as refused:
        _undo(owned_user, game, statement)

    assert "states an event after" in str(refused.value)


@pytest.mark.django_db(transaction=True)
def test_undo_is_refused_after_a_later_statement_moved_the_total(
    owned_user, owned_library, game, tracked
):
    _state(owned_user, game, 3)
    lower = _state(owned_user, game, 1)
    _state(owned_user, game, 2)

    with pytest.raises(CommandRejected) as refused:
        _undo(owned_user, game, lower)

    assert refused.value.sentence == CHANGED_SINCE
    assert "no longer counts" in str(refused.value)


@pytest.mark.django_db(transaction=True)
def test_a_second_undo_replays(owned_user, owned_library, game, tracked):
    statement = _state(owned_user, game, 2)
    undo_times_played(owned_user, game, statement.correlation, statement.stated)

    again = undo_times_played(owned_user, game, statement.correlation, statement.stated)

    assert again.outcome is CommandOutcome.REPLAYED
    assert _total(owned_library, tracked) == 0


@pytest.mark.django_db(transaction=True)
def test_undo_leaves_a_status_stated_since(owned_user, owned_library, game, tracked):
    statement = _state(owned_user, game, 1)
    _run(
        owned_user,
        RecordPlayerGameFacts(game_id=game.pk, status=PlayerGameStatus.SHELVED),
    )

    _undo(owned_user, game, statement)

    assert _status(tracked) == PlayerGameStatus.SHELVED


@pytest.mark.django_db(transaction=True)
def test_undo_of_a_double_submitted_statement_works(
    owned_user, owned_library, game, tracked
):
    correlation = uuid.uuid7()
    key = f"times-played-{correlation}"
    for _ in range(2):
        _run(
            owned_user,
            StatePlaythroughCount(game_id=game.pk, count=2),
            correlation_id=correlation,
            key=key,
        )
    _undo(owned_user, game, Statement(correlation, 2))

    assert _total(owned_library, tracked) == 0


@pytest.mark.django_db(transaction=True)
def test_undo_under_a_removed_game_is_refused(owned_user, game, tracked):
    statement = _state(owned_user, game, 2)
    PlayerGame.objects.filter(pk=tracked.pk).update(removed_at=timezone.now())

    with pytest.raises(CommandRejected) as refused:
        _undo(owned_user, game, statement)

    assert "removed" in refused.value.sentence


@pytest.mark.django_db(transaction=True)
def test_undo_of_a_statement_never_made_is_absent(owned_user, game, tracked):
    with pytest.raises(RowNotHeld):
        _undo(owned_user, game, Statement(uuid.uuid7(), 0))


# Edit


@pytest.mark.django_db(transaction=True)
def test_a_renamed_count_run_is_out_of_a_lowers_reach(
    owned_user, owned_library, game, tracked
):
    _state(owned_user, game, 2)
    for run in _live(owned_library, tracked):
        _run(
            owned_user,
            DescribePlaythrough(playthrough_id=run.pk, name="Named", note=None),
        )

    with pytest.raises(CommandRejected) as refused:
        _state(owned_user, game, 1)

    assert "Only 0" in refused.value.sentence


@pytest.mark.django_db(transaction=True)
def test_a_bare_run_beside_another_is_not_filled(
    owned_user, owned_library, game, tracked
):
    bare = _live(owned_library, tracked)[0]
    _dated_run(owned_user, game)

    _state(owned_user, game, 2)

    bare.refresh_from_db()
    assert bare.completion_recorded_at is None
    assert len(_live(owned_library, tracked)) == 3


@pytest.mark.django_db(transaction=True)
def test_a_lower_from_one_to_zero_voids_the_only_run(
    owned_user, owned_library, game, tracked
):
    _state(owned_user, game, 1)
    only = _live(owned_library, tracked)

    _state(owned_user, game, 0)

    runs = _live(owned_library, tracked)
    assert runs == only
    assert runs[0].completion_recorded_at is None


# Undo: provenance


def _stranger_library(django_user_model):
    return django_user_model.objects.create_user(username="stranger").library


@pytest.mark.parametrize("act", ["describe", "complete", "status"])
@pytest.mark.django_db(transaction=True)
def test_undo_of_an_act_that_is_no_count_is_absent(
    owned_user, owned_library, game, tracked, act
):
    run = _live(owned_library, tracked)[0]
    command = {
        "describe": DescribePlaythrough(playthrough_id=run.pk, name="Mine", note=None),
        "complete": CompletePlaythrough(
            playthrough_id=run.pk, when=DAY, note="", implies_status=True
        ),
        "status": RecordPlayerGameFacts(
            game_id=game.pk, status=PlayerGameStatus.SHELVED
        ),
    }[act]
    correlation = uuid.uuid7()
    _run(owned_user, command, correlation_id=correlation)

    with pytest.raises(RowNotHeld):
        _undo(owned_user, game, Statement(correlation, _total(owned_library, tracked)))


@pytest.mark.django_db(transaction=True)
def test_undo_of_another_games_count_is_absent(
    owned_user, owned_library, game, tracked
):
    other = Game.objects.create(library=owned_library, name="Tunic")
    track_game(owned_user, other, correlation_id=new_correlation_id())
    statement = _state(owned_user, other, 2)

    with pytest.raises(RowNotHeld):
        _undo(owned_user, game, statement)


# Undo: a run something names


@pytest.mark.parametrize("removed", [False, True], ids=["live", "removed"])
@pytest.mark.django_db(transaction=True)
def test_undo_is_refused_when_a_session_names_a_created_run(
    owned_user, owned_library, game, tracked, removed
):
    statement = _state(owned_user, game, 2)
    created = _live(owned_library, tracked)[-1]
    session = timed_row(created, timezone.now(), None)
    if removed:
        type(session).objects.filter(pk=session.pk).update(removed_at=timezone.now())

    with pytest.raises(CommandRejected) as refused:
        _undo(owned_user, game, statement)

    assert refused.value.sentence == CHANGED_SINCE
    assert "A row names" in str(refused.value)
    assert _total(owned_library, tracked) == 2


@pytest.mark.django_db(transaction=True)
def test_undo_is_refused_when_a_record_names_a_created_run(
    owned_user, owned_library, game, tracked
):
    statement = _state(owned_user, game, 2)
    record_row([_live(owned_library, tracked)[-1]])

    with pytest.raises(CommandRejected) as refused:
        _undo(owned_user, game, statement)

    assert "A row names" in str(refused.value)


@pytest.mark.django_db(transaction=True)
def test_a_lower_past_a_foreign_row_is_a_defect(
    owned_user, owned_library, game, tracked, django_user_model
):
    _state(owned_user, game, 2)
    newest = _live(owned_library, tracked)[-1]
    timed_row(
        newest, timezone.now(), None, library=_stranger_library(django_user_model)
    )

    with pytest.raises(RowUnreadable):
        _state(owned_user, game, 1)

    assert _total(owned_library, tracked) == 2


@pytest.mark.django_db(transaction=True)
def test_undo_past_a_foreign_row_is_a_defect(
    owned_user, owned_library, game, tracked, django_user_model
):
    statement = _state(owned_user, game, 2)
    timed_row(
        _live(owned_library, tracked)[-1],
        timezone.now(),
        None,
        library=_stranger_library(django_user_model),
    )

    with pytest.raises(RowUnreadable):
        _undo(owned_user, game, statement)

    assert _total(owned_library, tracked) == 2


# Undo: status


@pytest.mark.django_db(transaction=True)
def test_undo_of_a_raise_from_played_puts_played_back(
    owned_user, owned_library, game, tracked
):
    _run(
        owned_user,
        RecordPlayerGameFacts(game_id=game.pk, status=PlayerGameStatus.PLAYED),
    )
    statement = _state(owned_user, game, 1)

    _undo(owned_user, game, statement)

    assert _status(tracked) == PlayerGameStatus.PLAYED


@pytest.mark.django_db(transaction=True)
def test_undo_of_a_raise_from_completed_leaves_completed(
    owned_user, owned_library, game, tracked
):
    _run(
        owned_user,
        RecordPlayerGameFacts(game_id=game.pk, status=PlayerGameStatus.COMPLETED),
    )
    statement = _state(owned_user, game, 1)

    undone = undo_times_played(
        owned_user, game, statement.correlation, statement.stated
    )

    assert _status(tracked) == PlayerGameStatus.COMPLETED
    assert not undone.status_kept


@pytest.mark.django_db(transaction=True)
def test_undo_says_when_a_later_status_stood(owned_user, owned_library, game, tracked):
    statement = _state(owned_user, game, 1)
    _run(
        owned_user,
        RecordPlayerGameFacts(game_id=game.pk, status=PlayerGameStatus.SHELVED),
    )

    undone = undo_times_played(
        owned_user, game, statement.correlation, statement.stated
    )

    assert undone.status_kept


@pytest.mark.django_db(transaction=True)
def test_undo_of_a_lower_states_no_status_and_redates_nothing(
    owned_user, owned_library, game, tracked
):
    _state(owned_user, game, 2)
    statement = _state(owned_user, game, 0)
    status_before = _status(tracked)

    _undo(owned_user, game, statement)

    assert _status(tracked) == status_before
    runs = _live(owned_library, tracked)
    assert all(
        run.started is None
        and run.completed is None
        and run.start_recorded_at
        and run.completion_recorded_at
        for run in runs
    )
    assert set(dateless_runs(owned_library, tracked)) == set(runs)
