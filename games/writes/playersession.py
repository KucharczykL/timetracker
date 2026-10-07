"""State a session; answer a refusal.

An actor goes in here, not a request.
"""

import logging
import uuid
from datetime import datetime
from typing import NamedTuple

from django.contrib.auth.models import User
from django.utils import timezone

from games.commands.historical_playtime import HistoricalPlaytimeStatement
from games.commands.playergame import RecordPlayerGameFacts
from games.commands.playersession import (
    CorrectSessionTiming,
    CreateSession,
    DescribeSession,
    EndSession,
    MoveSessionToPlaythrough,
    RemoveSession,
    RestoreSession,
    StatedDevice,
    StatedRelease,
    TimedTiming,
    TimingStatement,
)
from games.commands.scope import checked_release
from games.commands.session_reclassification import (
    ReclassifySessionAsHistoricalPlaytime,
    UndoSessionReclassification,
)
from games.events.append import SourceMetadata
from games.events.dispatch import Command, CommandRejected, CommandResult, dispatch
from games.events.idempotency import IdempotencyKey
from games.events.playersession import PLAYERSESSION_RELEASE_CHANGED, ZoneName
from games.ids import PlayerSessionId
from games.models import (
    Device,
    Game,
    PlayerGameStatus,
    PlayerSession,
    Playthrough,
    UserLibrary,
)
from games.reads.calendar import calendar_day_zone
from games.reads.devices import held_devices
from games.reads.events import created_aggregate_id, dispatched_events
from games.reads.player_sessions import game_sessions
from games.reads.playthrough_runs import (
    library_runs,
    live_ordinary_runs,
    tracked_game,
)
from games.writes.answers import answered

logger = logging.getLogger("games")


class SessionDraft(NamedTuple):
    """What a person stated about one session."""

    playthrough_id: uuid.UUID
    timing: TimingStatement
    device_id: uuid.UUID | None
    note: str
    emulated: bool
    release_id: uuid.UUID | None


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
        #: Caller's key, else one per request.
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


def record_session(
    actor: User,
    draft: SessionDraft,
    *,
    implies_played: bool,
    correlation_id: uuid.UUID,
    idempotency_key: IdempotencyKey | None = None,
) -> uuid.UUID:
    """Record one session on the run the draft names; answer its id.

    A stated key absorbs its own repeat.
    """
    with answered("session"):
        result = _dispatch(
            CreateSession(
                playthrough_id=draft.playthrough_id,
                timing=draft.timing,
                device_id=draft.device_id,
                release_id=draft.release_id,
                note=draft.note,
                emulated=draft.emulated,
                implies_played=implies_played,
            ),
            actor=actor,
            library=actor.library,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
    return created_aggregate_id(result)


RELEASE_CLEARED_BY_THE_MOVE = (
    "The session no longer names a release: that one was of its old game."
)


def cleared_a_release(result: CommandResult) -> bool:
    """Whether a move cleared the session's Release."""
    return (
        dispatched_events(result)
        .filter(event_type=PLAYERSESSION_RELEASE_CHANGED.event_type)
        .exists()
    )


def refuse_an_unstatable_release(
    library: UserLibrary,
    session: PlayerSession,
    release_id: uuid.UUID | None,
    playthrough_id: uuid.UUID,
) -> None:
    """The Release rule, before any dispatch.

    A move to another game clears the held one, so
    there the stated one is checked anew.
    """
    if release_id is None:
        return
    run = (
        library_runs(library)
        .select_related("player_game")
        .filter(pk=playthrough_id)
        .first()
    )
    if run is None:
        #: The move refuses it, in its own words.
        return
    held = session.playthrough.player_game_id == run.player_game_id
    checked_release(
        library,
        release_id,
        game_id=run.player_game.game_id,
        held_id=session.release_id if held else None,
    )


def restate_session(
    actor: User,
    session: PlayerSession,
    draft: SessionDraft,
    *,
    implies_played: bool,
    correlation_id: uuid.UUID,
) -> None:
    """State the draft's differences onto a session.

    Five dispatches at most, one fact each, under one correlation:
    the timing, then the description, then the move, then the Release,
    then the Played the box implies.
    Each answers Unchanged for state the row holds, so a failed submit
    is finished by submitting again. The description names only the
    facts that differ, and is not dispatched when none does, since a
    description stating nothing is refused rather than Unchanged. The
    Release follows the move, which clears another game's.
    """
    with answered("session"):
        refuse_an_unstatable_release(
            actor.library, session, draft.release_id, draft.playthrough_id
        )
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
        moves = draft.playthrough_id != session.playthrough_id
        if moves:
            _dispatch(
                MoveSessionToPlaythrough(
                    session_id=session.pk, playthrough_id=draft.playthrough_id
                ),
                actor=actor,
                library=actor.library,
                correlation_id=correlation_id,
            )
        if draft.release_id != session.release_id or (
            moves and draft.release_id is not None
        ):
            _dispatch(
                DescribeSession(
                    session_id=session.pk, release=StatedRelease(draft.release_id)
                ),
                actor=actor,
                library=actor.library,
                correlation_id=correlation_id,
            )
        if implies_played:
            _dispatch(
                RecordPlayerGameFacts(
                    game_id=_run_game_id(actor.library, draft.playthrough_id),
                    implied_status=PlayerGameStatus.PLAYED,
                ),
                actor=actor,
                library=actor.library,
                correlation_id=correlation_id,
            )


def _run_game_id(library: UserLibrary, playthrough_id: uuid.UUID) -> uuid.UUID:
    """The catalog game the run belongs to."""
    return (
        Playthrough.objects.filter(library=library, pk=playthrough_id)
        .values_list("player_game__game_id", flat=True)
        .get()
    )


def correct_session(
    actor: User,
    session: PlayerSession,
    timing: TimingStatement,
    *,
    correlation_id: uuid.UUID,
    idempotency_key: IdempotencyKey | None = None,
    source_metadata: SourceMetadata | None = None,
) -> CommandResult:
    """State a session's whole timing again."""
    with answered("session"):
        return _dispatch(
            CorrectSessionTiming(session_id=session.pk, timing=timing),
            actor=actor,
            library=actor.library,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            source_metadata=source_metadata,
        )


def describe_session(
    actor: User,
    session: PlayerSession,
    *,
    note: str | None = None,
    device: StatedDevice | None = None,
    emulated: bool | None = None,
    release: StatedRelease | None = None,
    correlation_id: uuid.UUID,
    idempotency_key: IdempotencyKey | None = None,
    source_metadata: SourceMetadata | None = None,
) -> CommandResult:
    """State a fact; None is unstated."""
    with answered("session"):
        return _dispatch(
            DescribeSession(
                session_id=session.pk,
                note=note,
                device=device,
                emulated=emulated,
                release=release,
            ),
            actor=actor,
            library=actor.library,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            source_metadata=source_metadata,
        )


def move_session(
    actor: User,
    session: PlayerSession,
    playthrough_id: uuid.UUID,
    *,
    correlation_id: uuid.UUID,
    idempotency_key: IdempotencyKey | None = None,
    source_metadata: SourceMetadata | None = None,
) -> CommandResult:
    """State the session's run, at any game."""
    with answered("session"):
        return _dispatch(
            MoveSessionToPlaythrough(
                session_id=session.pk, playthrough_id=playthrough_id
            ),
            actor=actor,
            library=actor.library,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            source_metadata=source_metadata,
        )


def end_session(
    actor: User,
    session: PlayerSession,
    *,
    ended_at: datetime,
    ended_at_zone: ZoneName | None,
    correlation_id: uuid.UUID,
    idempotency_key: IdempotencyKey | None = None,
    source_metadata: SourceMetadata | None = None,
) -> CommandResult:
    """Finish a running Timed session at `ended_at`."""
    with answered("session"):
        return _dispatch(
            EndSession(
                session_id=session.pk, ended_at=ended_at, ended_at_zone=ended_at_zone
            ),
            actor=actor,
            library=actor.library,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            source_metadata=source_metadata,
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
    actor: User,
    session: PlayerSession,
    *,
    correlation_id: uuid.UUID,
    idempotency_key: IdempotencyKey | None = None,
    source_metadata: SourceMetadata | None = None,
) -> CommandResult:
    """Take a session out of the lists."""
    with answered("session"):
        return _dispatch(
            RemoveSession(session_id=session.pk),
            actor=actor,
            library=actor.library,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            source_metadata=source_metadata,
        )


def restore_session(
    actor: User,
    session: PlayerSession,
    *,
    correlation_id: uuid.UUID,
    idempotency_key: IdempotencyKey | None = None,
    source_metadata: SourceMetadata | None = None,
) -> CommandResult:
    """Put a removed session back."""
    with answered("session"):
        return _dispatch(
            RestoreSession(session_id=session.pk),
            actor=actor,
            library=actor.library,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            source_metadata=source_metadata,
        )


def reclassify_session(
    actor: User,
    session: PlayerSession,
    statement: HistoricalPlaytimeStatement,
    *,
    idempotency_key: IdempotencyKey,
    correlation_id: uuid.UUID,
    source_metadata: SourceMetadata | None = None,
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
            source_metadata=source_metadata,
        )
    return created_aggregate_id(result)


def undo_reclassification(
    actor: User,
    session: PlayerSession,
    *,
    correlation_id: uuid.UUID,
    idempotency_key: IdempotencyKey | None = None,
    source_metadata: SourceMetadata | None = None,
) -> CommandResult:
    """Remove the record; restore the session."""
    with answered("session"):
        return _dispatch(
            UndoSessionReclassification(session_id=session.pk),
            actor=actor,
            library=actor.library,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            source_metadata=source_metadata,
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


class ResumedDevice(NamedTuple):
    """The device and flag Resume states.

    The flag carries only with the last session's own device.
    """

    device: Device | None
    emulated: bool
    #: This library's device Resume did not carry.
    dropped: Device | None


class ResumedSession(NamedTuple):
    """The started session and its device."""

    session_id: PlayerSessionId
    device: ResumedDevice


def resumed_device(library: UserLibrary, last: PlayerSession | None) -> ResumedDevice:
    """Held or no device kept; else default."""
    dropped = None
    if last is not None:
        if last.device_id is None:
            return ResumedDevice(device=None, emulated=last.emulated, dropped=None)
        held = held_devices(library).filter(pk=last.device_id).first()
        if held is not None:
            return ResumedDevice(device=held, emulated=last.emulated, dropped=None)
        dropped = Device.objects.filter(library=library, pk=last.device_id).first()
        if dropped is None:
            #: Drift: another library's device.
            logger.error(
                "Library %s holds no device %s that session %s at game %s names.",
                library.pk,
                last.device_id,
                last.pk,
                last.playthrough.player_game.game_id,
            )
    return ResumedDevice(
        device=library.preferences.default_device, emulated=False, dropped=dropped
    )


def clone_session(
    actor: User, game: Game, *, correlation_id: uuid.UUID
) -> ResumedSession:
    """Start a Timed session on the latest run.

    Device and flag follow `resumed_device`; note empty.
    """
    with answered("session"):
        run = latest_ordinary_run(actor.library, game)
        if run is None:
            raise CommandRejected(
                f"Library {actor.library.pk} holds no live ordinary run at game "
                f"{game.pk} to resume on.",
                sentence="This game has no playthrough to record a session on.",
            )
        last = (
            game_sessions(actor.library, game)
            .select_related("playthrough__player_game")
            .order_by("-sort_instant", "-id")
            .first()
        )
        resumed = resumed_device(actor.library, last)
        result = _dispatch(
            CreateSession(
                playthrough_id=run.pk,
                timing=TimedTiming(
                    started_at=timezone.now(),
                    day_zone=calendar_day_zone(actor.library).key,
                ),
                device_id=None if resumed.device is None else resumed.device.pk,
                note="",
                emulated=resumed.emulated,
                implies_played=False,
            ),
            actor=actor,
            library=actor.library,
            correlation_id=correlation_id,
        )
    return ResumedSession(session_id=created_aggregate_id(result), device=resumed)
