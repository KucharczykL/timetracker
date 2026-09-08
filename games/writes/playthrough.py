"""State a run; answer a refusal.

An actor goes in here, not a request.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import NamedTuple, Protocol

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

    None is an endpoint the person said nothing about, and
    an ActStatement is the act, with no day where none was
    given. A note-only edit states neither act.
    """

    started: ActStatement | None
    completed: ActStatement | None
    note: str


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


class EndpointCommand(Protocol):
    """Builds a command about one endpoint.

    A callback protocol over the class itself, so a member
    of an EndpointStatement whose fields differ fails the
    type check rather than the dispatch.
    """

    def __call__(
        self,
        *,
        playthrough_id: uuid.UUID,
        when: TemporalValue | None,
        note: str,
    ) -> Command: ...


class EndpointStatement(NamedTuple):
    """How one endpoint is stated, and restated."""

    reads: Callable[[Playthrough], StatedEndpoint | None]
    first: EndpointCommand
    correction: EndpointCommand


_START = EndpointStatement(stated_start, StartPlaythrough, CorrectPlaythroughStart)
_COMPLETION = EndpointStatement(
    stated_completion, CompletePlaythrough, CorrectPlaythroughCompletion
)

#: One endpoint, and the act stated about it.
type Statement = tuple[EndpointStatement, ActStatement | None]


def _stated_day(act: ActStatement | None) -> TemporalValue | None:
    """The day an act states, or none."""
    return None if act is None else act.when


def _state_endpoint(
    actor: User,
    run: Playthrough,
    endpoint: EndpointStatement,
    act: ActStatement | None,
    *,
    correlation_id: uuid.UUID,
) -> None:
    """State one endpoint, first time or correction.

    An endpoint nobody stated is left alone: an act is
    recorded because a person recorded it, and a note-only
    edit records none.

    The choice is read before dispatch takes its lock, so
    a racer who states this endpoint first turns it stale
    and the command refuses a second statement in its own
    words. That refusal rises: reading the run again and
    correcting instead would overwrite the day the racer
    stated and answer this person success.

    A correction carries the note the endpoint already
    states, or it states a note nobody wrote.
    """
    if act is None:
        return
    stated = endpoint.reads(run)
    command_class = endpoint.first if stated is None else endpoint.correction
    note = "" if stated is None else stated.note
    _dispatch(
        command_class(playthrough_id=run.pk, when=act.when, note=note),
        actor=actor,
        library=actor.library,
        correlation_id=correlation_id,
    )


def _statement_order(
    run: Playthrough,
    started: ActStatement | None,
    completed: ActStatement | None,
) -> tuple[Statement, Statement]:
    """The order that states no reversed pair.

    One endpoint is stated at a time, so in between the run
    holds one new day beside one old one. Stating the start
    first reverses that pair for a run moved wholly later,
    and stating the completion first reverses it for a run
    moved wholly earlier. Only one of the two orders can
    reverse: both would need the draft itself reversed, and
    the caller refused that already.
    """
    start_first: tuple[Statement, Statement] = (
        (_START, started),
        (_COMPLETION, completed),
    )
    completion_first: tuple[Statement, Statement] = (
        (_COMPLETION, completed),
        (_START, started),
    )
    if endpoints_certainly_reversed(
        started=_stated_day(started), completed=run.completed
    ):
        return completion_first
    return start_first


def restate_run(
    actor: User,
    run: Playthrough,
    draft: RunDraft,
    *,
    correlation_id: uuid.UUID,
) -> None:
    """State the draft's differences onto a run.

    Three dispatches, not one build: each answers Unchanged
    for state the run holds, so a failed submit is finished
    by submitting again.
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
    started = draft.started
    completed = draft.completed
    #: Refused up front, because no act withdraws:
    #: a start commits, then the completion refuses.
    if endpoints_certainly_reversed(
        started=_stated_day(started), completed=_stated_day(completed)
    ):
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
    for endpoint, act in _statement_order(run, started, completed):
        _state_endpoint(actor, run, endpoint, act, correlation_id=correlation_id)


class RecordedRun(NamedTuple):
    """What stating a run did besides state it."""

    #: True where the game was tracked to hold the run.
    tracked_the_game: bool


def record_run(
    actor: User,
    game: Game,
    draft: RunDraft,
    *,
    correlation_id: uuid.UUID,
) -> RecordedRun:
    """State one run at a game.

    The run a tracked game already holds is filled in
    rather than left beside a second one: #679 gives every
    tracked game a run, and creating another would leave a
    never-played game holding an empty one forever.

    A game nothing tracks is tracked first, which is a
    library-visible act of its own -- hence the answer,
    which the request-shaped caller tells the person about.
    Dispatch refuses to nest, so no transaction spans the
    two: a refusal after tracking leaves the game tracked
    with no run stated, and stating it again finishes it.
    """
    with answered("playthrough"):
        try:
            _record_once(actor, game, draft, correlation_id=correlation_id)
        except PlayerGameNotTracked:
            #: One retry only. TrackGame states a run,
            #: so the branch runs again rather than re-dispatching.
            track_game(actor, game, correlation_id=correlation_id)
            _record_once(actor, game, draft, correlation_id=correlation_id)
            return RecordedRun(tracked_the_game=True)
    return RecordedRun(tracked_the_game=False)


def _record_once(
    actor: User,
    game: Game,
    draft: RunDraft,
    *,
    correlation_id: uuid.UUID,
) -> None:
    """Adopt the game's run, or create one.

    The absent row is refused here rather than left to the
    command: a game tracked between this read and the
    dispatch would let a creation through, leaving the new
    run beside the empty one that tracking just made. The
    refusal is the caller's signal to track and read again,
    and after tracking the row is certainly there.
    """
    tracked = PlayerGame.objects.filter(library=actor.library, game=game).first()
    if tracked is None:
        raise PlayerGameNotTracked(
            f"This library tracks no game {game.pk}, so it holds no run to fill "
            "in. TrackGame states one, and the caller states this again.",
            sentence="This game is not tracked yet. Reload the page and try again.",
        )
    adopted = run_to_adopt(actor.library, tracked)
    if adopted is not None:
        _restate(actor, adopted, draft, correlation_id=correlation_id)
        return
    _dispatch(
        CreatePlaythrough(
            game_id=game.pk,
            #: The acts the draft states; recording states both.
            started=draft.started,
            completed=draft.completed,
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
