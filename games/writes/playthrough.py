"""State a run; answer a refusal.

An actor goes in here, not a request.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import NamedTuple, Protocol

from django.contrib.auth.models import User

from games.commands.endpoint import certainly_reversed
from games.commands.playergame import PlayerGameNotTracked
from games.commands.playthrough import (
    ActStatement,
    CompletePlaythrough,
    CorrectPlaythroughCompletion,
    CorrectPlaythroughStart,
    CreatePlaythrough,
    DescribePlaythrough,
    MovePlaythroughToGame,
    RecordPlaythroughByName,
    RemovePlaythrough,
    RestorePlaythrough,
    StartPlaythrough,
    VoidPlaythroughCompletion,
    VoidPlaythroughStart,
)
from games.events.append import SourceMetadata
from games.events.dispatch import (
    Command,
    CommandOutcome,
    CommandRejected,
    CommandResult,
    RowUnreadable,
    dispatch,
)
from games.events.idempotency import IdempotencyKey
from games.events.playergame import PLAYERGAME_CREATED
from games.events.playthrough import PLAYTHROUGH_CREATED, PLAYTHROUGH_REMOVED
from games.ids import GameId
from games.models import (
    Game,
    PlayerGame,
    PlayerGameStatus,
    Playthrough,
    UserLibrary,
)
from games.reads.events import created_aggregate_id, dispatched_events
from games.reads.playthrough_endpoints import (
    StatedEndpoint,
    stated_completion,
    stated_start,
)
from games.reads.playthrough_runs import live_ordinary_runs, run_to_adopt
from games.writes.answers import CommandFailed, answered
from games.writes.endpoint import Act, endpoint_move
from games.writes.implied_status import (
    StatusAnswer,
    implied_status,
    state_implied_status,
)
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
    #: The run's catalog game; None states none.
    game_id: GameId | None = None


def _dispatch(
    command: Command,
    *,
    actor: User,
    library: UserLibrary,
    correlation_id: uuid.UUID,
    idempotency_key: IdempotencyKey | None = None,
    source_metadata: SourceMetadata | None = None,
) -> CommandResult:
    return dispatch(
        command,
        actor=actor,
        library=library,
        #: Caller's key, else one per request, which deduplicates
        #: nothing: each build absorbs a repeat.
        #:
        #: Not `or`: a blank key is falsy, so it would be minted
        #: over, and the caller that asked for one write would get
        #: a second on its retry rather than a refusal.
        idempotency_key=(
            str(uuid.uuid7()) if idempotency_key is None else idempotency_key
        ),
        correlation_id=correlation_id,
        source_metadata=source_metadata,
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
    move = endpoint_move(stated, act)
    command_class = endpoint.first if isinstance(move, Act) else endpoint.correction
    note = "" if stated is None else stated.note
    _dispatch(
        command_class(playthrough_id=run.pk, when=act.when, note=note),
        actor=actor,
        library=actor.library,
        correlation_id=correlation_id,
    )


def _state_first_act(
    actor: User,
    run: Playthrough,
    command: EndpointCommand,
    when: TemporalValue | None,
    *,
    correlation_id: uuid.UUID,
    idempotency_key: IdempotencyKey | None = None,
    source_metadata: SourceMetadata | None = None,
) -> CommandResult:
    """State one endpoint, never correcting it.

    A caller that means "this happened today" states a new
    act, so a run already holding that endpoint is refused
    rather than overwritten. The command reads the run
    under dispatch's lock, so a stale page cannot slip a
    correction past as a first statement.

    No note: the act carries none of its own, and the
    endpoint's note is the endpoint's to keep.
    """
    with answered("playthrough"):
        return _dispatch(
            command(playthrough_id=run.pk, when=when, note=""),
            actor=actor,
            library=actor.library,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            source_metadata=source_metadata,
        )


def start_run(
    actor: User,
    run: Playthrough,
    when: TemporalValue | None,
    *,
    correlation_id: uuid.UUID,
    idempotency_key: IdempotencyKey | None = None,
    source_metadata: SourceMetadata | None = None,
) -> CommandResult:
    """State that a run began, first time only."""
    return _state_first_act(
        actor,
        run,
        StartPlaythrough,
        when,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        source_metadata=source_metadata,
    )


def complete_run(
    actor: User,
    run: Playthrough,
    when: TemporalValue | None,
    *,
    correlation_id: uuid.UUID,
    idempotency_key: IdempotencyKey | None = None,
    source_metadata: SourceMetadata | None = None,
) -> CommandResult:
    """State that a run finished, first time only."""
    return _state_first_act(
        actor,
        run,
        CompletePlaythrough,
        when,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        source_metadata=source_metadata,
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
    if certainly_reversed(earlier=_stated_day(started), later=run.completed):
        return completion_first
    return start_first


class MovedRun(NamedTuple):
    """What a move did beside the run."""

    source: Game
    target: Game
    tracked_the_target: bool
    removed_a_placeholder: bool
    minted_a_placeholder: bool
    #: The word the endpoints newly stated there.
    stated_status: PlayerGameStatus | None
    status_refusal: CommandFailed | None


def restate_run(
    actor: User,
    run: Playthrough,
    draft: RunDraft,
    *,
    correlation_id: uuid.UUID,
) -> MovedRun | None:
    """State the draft's differences onto a run.

    One dispatch per fact, so a resubmit finishes.
    A move goes first; None where none happened.
    """
    with answered("playthrough"):
        #: Before the move: no act withdraws.
        _refuse_a_reversed_draft(run, draft)
        moved = _move(actor, run, draft.game_id, correlation_id=correlation_id)
        _restate(actor, run, draft, correlation_id=correlation_id)
    return moved


def _move(
    actor: User,
    run: Playthrough,
    game_id: GameId | None,
    *,
    correlation_id: uuid.UUID,
) -> MovedRun | None:
    """Move; state the status the endpoints imply."""
    if game_id is None or game_id == run.player_game.game_id:
        return None
    source = run.player_game.game
    idempotency_key = str(uuid.uuid7())
    result = _dispatch(
        MovePlaythroughToGame(playthrough_id=run.pk, game_id=game_id),
        actor=actor,
        library=actor.library,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
    )
    if result.outcome is CommandOutcome.UNCHANGED:
        return None
    #: Reloads the parent, so the target reads.
    run.refresh_from_db()
    target = run.player_game.game
    appended = set(dispatched_events(result).values_list("event_type", flat=True))
    status = implied_status(run)
    answer = (
        StatusAnswer(changed=False, refusal=None)
        if status is None
        else state_implied_status(
            actor,
            target,
            status,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
    )
    return MovedRun(
        source=source,
        target=target,
        tracked_the_target=PLAYERGAME_CREATED.event_type in appended,
        removed_a_placeholder=PLAYTHROUGH_REMOVED.event_type in appended,
        minted_a_placeholder=PLAYTHROUGH_CREATED.event_type in appended,
        stated_status=status if answer.changed else None,
        status_refusal=answer.refusal,
    )


def _refuse_a_reversed_draft(run: Playthrough, draft: RunDraft) -> None:
    """Refused up front, because no act withdraws."""
    if certainly_reversed(
        earlier=_stated_day(draft.started), later=_stated_day(draft.completed)
    ):
        raise CommandRejected(
            f"The statement about playthrough {run.pk} completes it before it "
            "began, and no run ends before it begins.",
            sentence="This run finished before it started. Check the days.",
        )


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
    #: A start commits, then the completion refuses.
    _refuse_a_reversed_draft(run, draft)
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
    """The run a statement reached, and how."""

    playthrough_id: uuid.UUID
    #: True where the game was tracked to hold the run.
    tracked_the_game: bool
    #: False where the run already stated what was asked.
    recorded: bool = True


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
    if draft.game_id not in (None, game.pk):
        raise ValueError(
            f"A draft naming game {draft.game_id} was recorded at game {game.pk}; "
            "a recorded run names its game once."
        )
    with answered("playthrough"):
        try:
            recorded = _record_once(actor, game, draft, correlation_id=correlation_id)
        except PlayerGameNotTracked:
            #: One retry only. TrackGame states a run,
            #: so the branch runs again rather than re-dispatching.
            track_game(actor, game, correlation_id=correlation_id)
            recorded = _record_once(actor, game, draft, correlation_id=correlation_id)
            return RecordedRun(playthrough_id=recorded, tracked_the_game=True)
    return RecordedRun(playthrough_id=recorded, tracked_the_game=False)


def _record_once(
    actor: User,
    game: Game,
    draft: RunDraft,
    *,
    correlation_id: uuid.UUID,
) -> uuid.UUID:
    """Adopt the game's run, or create one; answer its key.

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
        return adopted.pk
    result = _dispatch(
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
    return created_aggregate_id(result)


def void_start(
    actor: User,
    run: Playthrough,
    *,
    correlation_id: uuid.UUID,
    idempotency_key: IdempotencyKey | None = None,
    source_metadata: SourceMetadata | None = None,
) -> CommandResult:
    """Take back the record that the run began."""
    with answered("playthrough"):
        return _dispatch(
            VoidPlaythroughStart(playthrough_id=run.pk),
            actor=actor,
            library=actor.library,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            source_metadata=source_metadata,
        )


def void_completion(
    actor: User,
    run: Playthrough,
    *,
    correlation_id: uuid.UUID,
    idempotency_key: IdempotencyKey | None = None,
    source_metadata: SourceMetadata | None = None,
) -> CommandResult:
    """Take back the record that the run finished."""
    with answered("playthrough"):
        return _dispatch(
            VoidPlaythroughCompletion(playthrough_id=run.pk),
            actor=actor,
            library=actor.library,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            source_metadata=source_metadata,
        )


def remove_run(
    actor: User,
    run: Playthrough,
    *,
    correlation_id: uuid.UUID,
    idempotency_key: IdempotencyKey | None = None,
    source_metadata: SourceMetadata | None = None,
) -> CommandResult:
    """Take a run out of the lists."""
    with answered("playthrough"):
        return _dispatch(
            RemovePlaythrough(playthrough_id=run.pk),
            actor=actor,
            library=actor.library,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            source_metadata=source_metadata,
        )


def restore_run(
    actor: User,
    run: Playthrough,
    *,
    correlation_id: uuid.UUID,
    idempotency_key: IdempotencyKey | None = None,
    source_metadata: SourceMetadata | None = None,
) -> CommandResult:
    """Put a removed run back."""
    with answered("playthrough"):
        return _dispatch(
            RestorePlaythrough(playthrough_id=run.pk),
            actor=actor,
            library=actor.library,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            source_metadata=source_metadata,
        )


def record_named_run(
    actor: User,
    game: Game,
    name: str,
    *,
    correlation_id: uuid.UUID,
) -> RecordedRun:
    """State the run a person typed a name for.

    The command decides between naming the placeholder and
    creating one more, under the stream head's lock.

    A game nothing tracks is tracked first, as `record_run`
    tracks it. Tracking states a run, and that run is a
    placeholder, so the second statement names it and the
    game ends with one named run.
    """
    command = RecordPlaythroughByName(game_id=game.pk, name=name)
    with answered("playthrough"):
        try:
            result = _dispatch(
                command,
                actor=actor,
                library=actor.library,
                correlation_id=correlation_id,
            )
        except PlayerGameNotTracked:
            #: One retry only, as `record_run` retries.
            track_game(actor, game, correlation_id=correlation_id)
            result = _dispatch(
                command,
                actor=actor,
                library=actor.library,
                correlation_id=correlation_id,
            )
            return _named_run(actor, game, command, result, tracked_the_game=True)
        return _named_run(actor, game, command, result, tracked_the_game=False)


def _named_run(
    actor: User,
    game: Game,
    command: RecordPlaythroughByName,
    result: CommandResult,
    *,
    tracked_the_game: bool,
) -> RecordedRun:
    """The run the dispatch reached.

    An appended outcome names it in its first event. An
    Unchanged one appended nothing, so the row is read
    back by the name it already states -- the oldest,
    where an earlier act left two of them.
    """
    if result.sequences is not None:
        return RecordedRun(
            playthrough_id=created_aggregate_id(result),
            tracked_the_game=tracked_the_game,
        )
    tracked = PlayerGame.objects.filter(library=actor.library, game=game).first()
    run = (
        None
        if tracked is None
        else live_ordinary_runs(actor.library, tracked)
        .filter(name__iexact=command.name)
        .first()
    )
    if run is None:
        #: Read outside the lock that answered Unchanged: a removal
        #: between the two lands here.
        raise RowUnreadable(
            f"RecordPlaythroughByName answered Unchanged about name "
            f"{command.name!r} at game {game.pk}, and library "
            f"{actor.library.pk} holds no live ordinary run of that name."
        )
    return RecordedRun(
        playthrough_id=run.pk, tracked_the_game=tracked_the_game, recorded=False
    )
