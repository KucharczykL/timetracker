"""State a run; answer a refused statement.

Takes an actor, not a request.
The view half makes it a toast.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import NamedTuple

from django.contrib.auth.models import User

from games.commands.playergame import PlayerGameNotTracked
from games.commands.playthrough import (
    ActStatement,
    CompletePlaythrough,
    CorrectPlaythroughCompletion,
    CorrectPlaythroughStart,
    CreatePlaythrough,
    DescribePlaythrough,
    RemovePlaythrough,
    StartPlaythrough,
    endpoints_certainly_reversed,
)
from games.events.dispatch import Command, CommandRejected, dispatch
from games.models import Game, PlayerGame, Playthrough, UserLibrary
from games.reads.playthrough_endpoints import (
    StatedEndpoint,
    stated_completion,
    stated_start,
)
from games.reads.playthrough_runs import run_to_adopt
from games.writes.answers import answered
from games.writes.playergame import track_game
from timetracker.temporal import TemporalValue


@dataclass(frozen=True, slots=True)
class RunDraft:
    """What a person stated about one run.

    Plain dates, because the form states days. The act rule turns them
    into two acts: a day where one was given, and the act with no day
    where none was.
    """

    started: date | None
    ended: date | None
    note: str


def _stated_day(value: date | None) -> TemporalValue | None:
    """The day at day precision, or no day at all."""
    return None if value is None else TemporalValue.from_day(value)


def _dispatch(
    command: Command,
    *,
    actor: User,
    library: UserLibrary,
    correlation_id: uuid.UUID,
) -> None:
    dispatch(
        command,
        actor=actor,
        library=library,
        #: Deduplicates nothing; each build absorbs a repeat.
        idempotency_key=str(uuid.uuid7()),
        correlation_id=correlation_id,
    )


class EndpointStatement(NamedTuple):
    """How one endpoint is stated, the first time and after it."""

    reads: Callable[[Playthrough], StatedEndpoint | None]
    first: type[Command]
    correction: type[Command]


_ENDPOINTS: tuple[EndpointStatement, ...] = (
    EndpointStatement(stated_start, StartPlaythrough, CorrectPlaythroughStart),
    EndpointStatement(
        stated_completion, CompletePlaythrough, CorrectPlaythroughCompletion
    ),
)


def _state_endpoint(
    actor: User,
    run: Playthrough,
    endpoint: EndpointStatement,
    when: TemporalValue | None,
    *,
    correlation_id: uuid.UUID,
) -> None:
    """State one endpoint, as a first statement or as a correction.

    Which of the two is read before dispatch takes its lock, so a
    second request on the same run can make the choice stale and the
    command refuses it. A refusal re-reads the run and states it once
    more -- one attempt, never a loop, the shape tracking uses.

    A correction carries the note the endpoint already states: #684
    wrote every endpoint note blank and put the row's note on the run,
    so a day-only correction that passed a fresh blank would state a
    note nobody wrote.
    """
    for attempt in (1, 2):
        stated = endpoint.reads(run)
        command_class = endpoint.first if stated is None else endpoint.correction
        note = "" if stated is None else stated.note
        try:
            _dispatch(
                command_class(playthrough_id=run.pk, when=when, note=note),  # type: ignore[call-arg]
                actor=actor,
                library=actor.library,
                correlation_id=correlation_id,
            )
            return
        except CommandRejected:
            if attempt == 2:
                raise
            run.refresh_from_db()


def restate_run(
    actor: User,
    run: Playthrough,
    draft: RunDraft,
    *,
    correlation_id: uuid.UUID,
) -> None:
    """State the draft onto a run that exists, differences only.

    Three dispatches rather than one build: each command answers
    Unchanged for state the run already holds, so a submit that fails
    after the first act is finished by submitting again.
    """
    with answered("playthrough"):
        _restate(actor, run, draft, correlation_id=correlation_id)


def _restate(
    actor: User,
    run: Playthrough,
    draft: RunDraft,
    *,
    correlation_id: uuid.UUID,
) -> None:
    """The statements themselves, inside a caller's answer."""
    started = _stated_day(draft.started)
    completed = _stated_day(draft.ended)
    #: Before the first dispatch. On the three-dispatch path a start
    #: commits and only the completion would refuse, and no command
    #: withdraws a stated act.
    if endpoints_certainly_reversed(started=started, completed=completed):
        raise CommandRejected(
            f"The statement about playthrough {run.pk} completes it before it "
            "began, and no run ends before it begins.",
            sentence="This run finished before it started. Check the days.",
        )
    if draft.note.strip() != run.note:
        _dispatch(
            DescribePlaythrough(playthrough_id=run.pk, name=None, note=draft.note),
            actor=actor,
            library=actor.library,
            correlation_id=correlation_id,
        )
        run.refresh_from_db()
    for endpoint, when in zip(_ENDPOINTS, (started, completed), strict=True):
        _state_endpoint(actor, run, endpoint, when, correlation_id=correlation_id)


def record_run(
    actor: User,
    game: Game,
    draft: RunDraft,
    *,
    correlation_id: uuid.UUID,
) -> None:
    """State one run at a game.

    The first run of a tracked game is the one it already holds: #679
    states a run the moment a library tracks a game, and a second one
    beside it would leave every never-played game with an empty run
    forever.
    """
    with answered("playthrough"):
        try:
            _record_once(actor, game, draft, correlation_id=correlation_id)
        except PlayerGameNotTracked:
            #: One retry, never a loop. TrackGame states a run of its
            #: own, so the branch is read again rather than the command
            #: re-dispatched, which would leave a second run beside it.
            track_game(actor, game, correlation_id=correlation_id)
            _record_once(actor, game, draft, correlation_id=correlation_id)


def _record_once(
    actor: User,
    game: Game,
    draft: RunDraft,
    *,
    correlation_id: uuid.UUID,
) -> None:
    """Adopt the run the game already holds, or create one."""
    tracked = PlayerGame.objects.filter(library=actor.library, game=game).first()
    adopted = None if tracked is None else run_to_adopt(actor.library, tracked)
    if adopted is not None:
        _restate(actor, adopted, draft, correlation_id=correlation_id)
        return
    #: An untracked game reaches the command, which raises
    #: PlayerGameNotTracked for the retry above to read.
    _dispatch(
        CreatePlaythrough(
            game_id=game.pk,
            #: Both acts, always: a run recorded here happened.
            started=ActStatement(_stated_day(draft.started)),
            completed=ActStatement(_stated_day(draft.ended)),
            note=draft.note,
        ),
        actor=actor,
        library=actor.library,
        correlation_id=correlation_id,
    )


def remove_run(actor: User, run: Playthrough, *, correlation_id: uuid.UUID) -> None:
    """Take a run out of the lists."""
    with answered("playthrough"):
        _dispatch(
            RemovePlaythrough(playthrough_id=run.pk),
            actor=actor,
            library=actor.library,
            correlation_id=correlation_id,
        )
