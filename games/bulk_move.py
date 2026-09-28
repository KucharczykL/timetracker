"""One session moved by a bulk act, and back."""

import logging
import uuid

from django.contrib.auth.models import User
from django.http import Http404

from games.bulk_actions import RowOutcome
from games.bulk_sessions import session_of
from games.events.dispatch import CommandRejected, RowUnreadable
from games.events.idempotency import IdempotencyKey
from games.events.playersession import PLAYERSESSION_CREATED, PLAYERSESSION_MOVED
from games.events.playthrough import PLAYTHROUGH_REMOVED
from games.models import (
    LibraryEvent,
    PlayerSession,
    Playthrough,
    PlaythroughKind,
    UserLibrary,
)
from games.reads.events import aggregate_events, batch_events
from games.reads.playthrough_referrers import BLOCKING_REFERRERS, rows_naming
from games.reads.playthrough_runs import library_runs
from games.writes.answers import CONFLICT_STATUS, CommandFailed, answered
from games.writes.playersession import move_session
from games.writes.playthrough import remove_run, restore_run

logger = logging.getLogger("games")

#: A bulk act's declared name.
type ActName = str  # e.g. "session.edit"

#: What a gone target refuses.
TARGET_GONE = (
    "That playthrough is no longer available. Choose another one, or reload "
    "the list and start again."
)

#: What one row refuses.
ANOTHER_GAME = (
    "That session is at another game, so it cannot go to this playthrough. "
    "It was left as it is."
)

#: The events that state a session's run.
RUN_STATED = (PLAYERSESSION_CREATED.event_type, PLAYERSESSION_MOVED.event_type)

#: What an Undo refuses.
NOT_MOVED_BY_THIS_BATCH = (
    "That session was not moved by this batch, so its playthrough was left as it is."
)
NO_EARLIER_RUN = (
    "Where that session was before cannot be read, so its playthrough was "
    "left as it is."
)
SOURCE_TAKEN_AWAY = (
    "The playthrough that session came from was removed after this batch, so "
    "its playthrough was left as it is. Put that playthrough back first."
)


def _source(act: ActName) -> dict[str, object]:
    return {"bulk": {"action": act}}


def target_run(library: UserLibrary, key: uuid.UUID) -> Playthrough:
    """The run a batch moves rows to."""
    run = library_runs(library).filter(pk=key).first()
    if run is None:
        raise CommandRejected(
            f"playthrough {key} is no live ordinary run of library {library.pk}",
            sentence=TARGET_GONE,
        )
    return run


def refuse_another_game(session: PlayerSession, target: Playthrough) -> None:
    """A run belongs to one game."""
    if session.playthrough.player_game_id != target.player_game_id:
        raise CommandRejected(
            f"session {session.pk} is at game "
            f"{session.playthrough.player_game_id} and playthrough "
            f"{target.pk} at {target.player_game_id}",
            sentence=ANOTHER_GAME,
        )


def move_row(
    actor: User,
    session: PlayerSession,
    target: Playthrough,
    *,
    act: ActName,
    idempotency_key: IdempotencyKey,
    correlation_id: uuid.UUID,
) -> RowOutcome:
    """One session moved; the bucket it left."""
    outcome = RowOutcome.of(
        move_session(
            actor,
            session,
            target.pk,
            idempotency_key=f"{idempotency_key}-move",
            correlation_id=correlation_id,
            source_metadata=_source(act),
        )
    )
    if outcome is RowOutcome.MOVED:
        _remove_the_emptied_bucket(
            actor, session.pk, act, idempotency_key, correlation_id
        )
    return outcome


def _remove_the_emptied_bucket(
    actor: User,
    session_id: uuid.UUID,
    act: ActName,
    idempotency_key: IdempotencyKey,
    correlation_id: uuid.UUID,
) -> None:
    """Take away the bucket this row emptied.

    The run the row came from, never every bucket the game
    holds: an act that removed a bucket it did not empty
    would remove a row its own inverse never puts back.

    Read from the batch's own events, because a chunk posted
    twice replays the move as moved, and the row then names
    the target already.

    A batch that moved no such row removes nothing. A
    broken stream is a defect and ends the batch.
    """
    with answered("session"):
        try:
            emptied = run_before(actor.library, session_id, correlation_id)
        except CommandRejected:
            #: This batch moved no such row.
            return
    bucket = Playthrough.objects.filter(
        library=actor.library,
        pk=emptied,
        kind=PlaythroughKind.IMPORTED_HISTORY,
        removed_at__isnull=True,
    ).first()
    if bucket is None:
        return
    if any(rows_naming(referrer, bucket).exists() for referrer in BLOCKING_REFERRERS):
        return
    try:
        remove_run(
            actor,
            bucket,
            idempotency_key=f"{idempotency_key}-bucket",
            correlation_id=correlation_id,
            source_metadata=_source(act),
        )
    except CommandFailed as failure:
        if failure.status_code != CONFLICT_STATUS:
            #: Ours, not theirs: the batch ends.
            raise
        logger.info(
            "[bulk]: %s left bucket %s of library %s under %s: %s",
            act,
            bucket.pk,
            actor.library.pk,
            correlation_id,
            failure.message,
        )
    except Http404 as absent:
        #: A race, not a defect.
        logger.info(
            "[bulk]: %s met a bucket library %s no longer holds: %s",
            act,
            actor.library.pk,
            absent,
        )


# ── Backward ─────────────────────────────────────────────────────────────────


def moved_by(library: UserLibrary, session_id: uuid.UUID, batch_id: uuid.UUID) -> bool:
    """Whether the batch moved the session."""
    return (
        batch_events(library, batch_id)
        .filter(aggregate_id=session_id, event_type=PLAYERSESSION_MOVED.event_type)
        .exists()
    )


def run_before(
    library: UserLibrary, session_id: uuid.UUID, batch_id: uuid.UUID
) -> uuid.UUID:
    """The run the session sat on before."""
    events = list(aggregate_events(library, session_id))
    moved = next(
        (
            event
            for event in events
            if event.correlation_id == batch_id
            and event.event_type == PLAYERSESSION_MOVED.event_type
        ),
        None,
    )
    if moved is None:
        raise CommandRejected(
            f"batch {batch_id} moved no session {session_id}",
            sentence=NOT_MOVED_BY_THIS_BATCH,
        )
    earlier = [
        event
        for event in events
        if event.sequence < moved.sequence and event.event_type in RUN_STATED
    ]
    if not earlier:
        raise RowUnreadable(
            f"session {session_id} of library {library.pk} states "
            f"{moved.event_type} at sequence {moved.sequence} and no run "
            "before it"
        )
    return _run_of(earlier[-1])


def _run_of(event: LibraryEvent) -> uuid.UUID:
    """The run a created or moved payload states."""
    run = event.payload.get("playthrough")
    if not isinstance(run, str):
        raise RowUnreadable(f"event {event.pk} states playthrough {run!r}")
    try:
        return uuid.UUID(run)
    except ValueError as error:
        raise RowUnreadable(f"event {event.pk} states playthrough {run!r}") from error


def _put_back_the_run(
    actor: User,
    act: ActName,
    batch_id: uuid.UUID,
    run_id: uuid.UUID,
    idempotency_key: IdempotencyKey,
    correlation_id: uuid.UUID,
) -> None:
    """Restore the run this batch emptied.

    Only that one. `RestorePlaythrough` puts back a run of
    any kind, so an inverse restoring whatever it found
    removed would also resurrect an ordinary run somebody
    removed by hand after the batch emptied it.

    Before the move, because a move onto a removed run is
    refused.
    """
    with answered("session"):
        run = Playthrough.objects.filter(library=actor.library, pk=run_id).first()
        if run is None:
            raise CommandRejected(
                f"playthrough {run_id} is not library {actor.library.pk}'s",
                sentence=NO_EARLIER_RUN,
            )
        ours = (
            batch_events(actor.library, batch_id)
            .filter(aggregate_id=run_id, event_type=PLAYTHROUGH_REMOVED.event_type)
            .exists()
        )
        if not ours and run.removed_at is not None:
            raise CommandRejected(
                f"playthrough {run_id} was removed outside batch {batch_id}",
                sentence=SOURCE_TAKEN_AWAY,
            )
    if not ours:
        return
    restore_run(
        actor,
        run,
        idempotency_key=f"{idempotency_key}-restore",
        correlation_id=correlation_id,
        source_metadata=_source(act),
    )


def move_back_row(
    actor: User,
    session_id: uuid.UUID,
    *,
    act: ActName,
    undoes: uuid.UUID,
    idempotency_key: IdempotencyKey,
    correlation_id: uuid.UUID,
) -> RowOutcome:
    """One session back to its earlier run."""
    with answered("session"):
        earlier = run_before(actor.library, session_id, undoes)
    _put_back_the_run(actor, act, undoes, earlier, idempotency_key, correlation_id)
    return RowOutcome.of(
        move_session(
            actor,
            session_of(actor, session_id),
            earlier,
            idempotency_key=f"{idempotency_key}-move",
            correlation_id=correlation_id,
            source_metadata=_source(act),
        )
    )
