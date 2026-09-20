"""State a session; answer a refusal.

An actor goes in here, not a request.
"""

import uuid
from datetime import datetime
from typing import NamedTuple

from django.contrib.auth.models import User
from django.utils import timezone

from games.commands.historical_playtime import HistoricalPlaytimeStatement
from games.commands.playersession import (
    CorrectSessionTiming,
    CreateSession,
    DescribeSession,
    EndSession,
    MoveSessionToPlaythrough,
    RemoveSession,
    RestoreSession,
    StatedDevice,
    TimedTiming,
    TimingStatement,
)
from games.commands.session_reclassification import (
    ReclassifySessionAsHistoricalPlaytime,
    UndoSessionReclassification,
)
from games.events.dispatch import Command, CommandRejected, CommandResult, dispatch
from games.events.idempotency import IdempotencyKey
from games.events.playersession import ZoneName
from games.models import Game, LibraryEvent, PlayerSession, Playthrough, UserLibrary
from games.reads.calendar import calendar_day_zone
from games.reads.playthrough_runs import live_ordinary_runs, tracked_game
from games.writes.answers import answered


class SessionDraft(NamedTuple):
    """What a person stated about one session."""

    playthrough_id: uuid.UUID
    timing: TimingStatement
    device_id: uuid.UUID | None
    note: str
    emulated: bool


def _dispatch(
    command: Command,
    *,
    actor: User,
    library: UserLibrary,
    correlation_id: uuid.UUID,
    idempotency_key: IdempotencyKey | None = None,
) -> CommandResult:
    return dispatch(
        command,
        actor=actor,
        library=library,
        #: Caller's key, else none; builds absorb repeats.
        idempotency_key=idempotency_key or str(uuid.uuid7()),
        correlation_id=correlation_id,
    )


def _created_id(result: CommandResult) -> uuid.UUID:
    """The row a creation wrote: its event's aggregate id."""
    assert result.sequences is not None
    return LibraryEvent.objects.get(
        stream_id=result.stream_id, sequence=result.sequences.first
    ).aggregate_id


def record_session(
    actor: User,
    draft: SessionDraft,
    *,
    correlation_id: uuid.UUID,
    idempotency_key: IdempotencyKey | None = None,
) -> uuid.UUID:
    """Record one session on the run the draft names; answer its id.

    A key the caller states absorbs its own repeat.
    """
    with answered("session"):
        result = _dispatch(
            CreateSession(
                playthrough_id=draft.playthrough_id,
                timing=draft.timing,
                device_id=draft.device_id,
                note=draft.note,
                emulated=draft.emulated,
            ),
            actor=actor,
            library=actor.library,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
    return _created_id(result)


def restate_session(
    actor: User,
    session: PlayerSession,
    draft: SessionDraft,
    *,
    correlation_id: uuid.UUID,
) -> None:
    """State the draft's differences onto a session.

    Three dispatches at most, one fact each, under one correlation:
    the timing, then the description, then the move. Each answers
    Unchanged for state the row holds, so a failed submit is finished
    by submitting again. The description names only the facts that
    differ, and is not dispatched when none does, since a description
    stating nothing is refused rather than Unchanged.
    """
    with answered("session"):
        _dispatch(
            CorrectSessionTiming(session_id=session.pk, timing=draft.timing),
            actor=actor,
            library=actor.library,
            correlation_id=correlation_id,
        )
        note = draft.note.strip()
        description = (
            DescribeSession(
                session_id=session.pk,
                note=None if note == session.note else note,
                device=(
                    None
                    if draft.device_id == session.device_id
                    else StatedDevice(draft.device_id)
                ),
                emulated=None if draft.emulated == session.emulated else draft.emulated,
            )
            if (
                note != session.note
                or draft.device_id != session.device_id
                or draft.emulated != session.emulated
            )
            else None
        )
        if description is not None:
            _dispatch(
                description,
                actor=actor,
                library=actor.library,
                correlation_id=correlation_id,
            )
        if draft.playthrough_id != session.playthrough_id:
            _dispatch(
                MoveSessionToPlaythrough(
                    session_id=session.pk, playthrough_id=draft.playthrough_id
                ),
                actor=actor,
                library=actor.library,
                correlation_id=correlation_id,
            )


def correct_session(
    actor: User,
    session: PlayerSession,
    timing: TimingStatement,
    *,
    correlation_id: uuid.UUID,
) -> None:
    """State a session's whole timing again."""
    with answered("session"):
        _dispatch(
            CorrectSessionTiming(session_id=session.pk, timing=timing),
            actor=actor,
            library=actor.library,
            correlation_id=correlation_id,
        )


def describe_session(
    actor: User,
    session: PlayerSession,
    *,
    note: str | None = None,
    device: StatedDevice | None = None,
    emulated: bool | None = None,
    correlation_id: uuid.UUID,
) -> None:
    """State note, device or emulated; None is unstated."""
    with answered("session"):
        _dispatch(
            DescribeSession(
                session_id=session.pk, note=note, device=device, emulated=emulated
            ),
            actor=actor,
            library=actor.library,
            correlation_id=correlation_id,
        )


def move_session(
    actor: User,
    session: PlayerSession,
    playthrough_id: uuid.UUID,
    *,
    correlation_id: uuid.UUID,
) -> None:
    """State the session's run, at any game."""
    with answered("session"):
        _dispatch(
            MoveSessionToPlaythrough(
                session_id=session.pk, playthrough_id=playthrough_id
            ),
            actor=actor,
            library=actor.library,
            correlation_id=correlation_id,
        )


def end_session(
    actor: User,
    session: PlayerSession,
    *,
    ended_at: datetime,
    ended_at_zone: ZoneName | None,
    correlation_id: uuid.UUID,
) -> None:
    """Finish a running Timed session at `ended_at`."""
    with answered("session"):
        _dispatch(
            EndSession(
                session_id=session.pk, ended_at=ended_at, ended_at_zone=ended_at_zone
            ),
            actor=actor,
            library=actor.library,
            correlation_id=correlation_id,
        )


def reset_session(
    actor: User,
    session: PlayerSession,
    *,
    started_at: datetime,
    started_at_zone: ZoneName | None,
    correlation_id: uuid.UUID,
) -> None:
    """Move a running Timed session's start to `started_at`.

    A correction, not a first statement: the row keeps its day zone,
    and the start takes the zone the browser stood in.
    """
    with answered("session"):
        if not is_running(session):
            raise CommandRejected(
                f"Session {session.pk} is not a running Timed row, so its start "
                "is not reset; the edit form corrects it.",
                sentence="Only a running session's start can be reset to now.",
            )
        assert session.day_zone is not None
        _dispatch(
            CorrectSessionTiming(
                session_id=session.pk,
                timing=TimedTiming(
                    started_at=started_at,
                    day_zone=session.day_zone,
                    started_at_zone=started_at_zone,
                ),
            ),
            actor=actor,
            library=actor.library,
            correlation_id=correlation_id,
        )


def remove_session(
    actor: User, session: PlayerSession, *, correlation_id: uuid.UUID
) -> None:
    """Take a session out of the lists."""
    with answered("session"):
        _dispatch(
            RemoveSession(session_id=session.pk),
            actor=actor,
            library=actor.library,
            correlation_id=correlation_id,
        )


def restore_session(
    actor: User, session: PlayerSession, *, correlation_id: uuid.UUID
) -> None:
    """Put a removed session back."""
    with answered("session"):
        _dispatch(
            RestoreSession(session_id=session.pk),
            actor=actor,
            library=actor.library,
            correlation_id=correlation_id,
        )


def reclassify_session(
    actor: User,
    session: PlayerSession,
    statement: HistoricalPlaytimeStatement,
    *,
    idempotency_key: IdempotencyKey,
    correlation_id: uuid.UUID,
) -> uuid.UUID:
    """Make the session a record; answer its id."""
    with answered("session"):
        result = _dispatch(
            ReclassifySessionAsHistoricalPlaytime(
                session_id=session.pk, statement=statement
            ),
            actor=actor,
            library=actor.library,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
    return _created_id(result)


def undo_reclassification(
    actor: User, session: PlayerSession, *, correlation_id: uuid.UUID
) -> CommandResult:
    """Remove the record; restore the session."""
    with answered("session"):
        return _dispatch(
            UndoSessionReclassification(session_id=session.pk),
            actor=actor,
            library=actor.library,
            correlation_id=correlation_id,
        )


def is_running(session: PlayerSession) -> bool:
    """A Timed row with no end yet."""
    return session.timing_mode == "timed" and session.ended_at is None


def latest_ordinary_run(library: UserLibrary, game: Game) -> Playthrough | None:
    """The game's latest live ordinary run, where the library tracks it.

    Never the bucket: a person records on a run.
    """
    tracked = tracked_game(library, game)
    if tracked is None:
        return None
    return live_ordinary_runs(library, tracked).order_by("-created_at", "-pk").first()


def clone_session(
    actor: User,
    game: Game,
    *,
    device_id: uuid.UUID | None,
    emulated: bool,
    correlation_id: uuid.UUID,
) -> uuid.UUID:
    """Start a session now on the game's latest live ordinary run.

    The device and the emulated flag are the resumed session's; the
    note is empty, and the day is counted in the library's calendar.
    """
    with answered("session"):
        run = latest_ordinary_run(actor.library, game)
        if run is None:
            raise CommandRejected(
                f"Library {actor.library.pk} holds no live ordinary run at game "
                f"{game.pk} to resume on.",
                sentence="This game has no playthrough to record a session on.",
            )
        result = _dispatch(
            CreateSession(
                playthrough_id=run.pk,
                timing=TimedTiming(
                    started_at=timezone.now(),
                    day_zone=calendar_day_zone(actor.library).key,
                ),
                device_id=device_id,
                note="",
                emulated=emulated,
            ),
            actor=actor,
            library=actor.library,
            correlation_id=correlation_id,
        )
    return _created_id(result)
