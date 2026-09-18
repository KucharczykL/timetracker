"""Its own module: the act spans two aggregates."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar

from games.commands.historical_playtime import (
    HistoricalPlaytimeStatement,
    _live_runs,
    created_event,
    normalized_statement,
)
from games.commands.historical_playtime import (
    _refuse_under_a_removed_parent as _refuse_under_the_records_removed_parent,
)
from games.commands.playersession import (
    SESSION_REMOVED,
    _refuse_under_a_removed_parent,
    _session_run,
    library_session,
    live_record_from,
)
from games.commands.playthrough import refuse_unless_live
from games.commands.scope import library_device, library_device_row
from games.events.dispatch import (
    Command,
    CommandContext,
    CommandName,
    CommandRejected,
    RowUnreadable,
)
from games.events.historical_playtime import historicalplaytime_removed
from games.events.playersession import (
    playersession_reclassified,
    playersession_restored,
)
from games.events.vocabulary import NewEvent, Unchanged
from games.models import (
    HistoricalPlaytime,
    HistoricalPlaytimeProvenance,
    PlayerSession,
    PlayerSessionTimingMode,
)
from timetracker.temporal import TemporalValue

STILL_RUNNING = (
    "That session is still running. Finish it before recording it as "
    "historical playtime."
)
ANOTHER_GAME = (
    "Historical playtime made from a session belongs to that session's game. "
    "Choose one of its playthroughs."
)
ALREADY_RECORDED = (
    "That session is already recorded as historical playtime. Undo that "
    "first to record it differently."
)
NEVER_RECLASSIFIED = (
    "That session was never recorded as historical playtime, so there is "
    "nothing to undo."
)
RESTATED_SINCE = (
    "That record was edited after it was made from the session, so undoing "
    "would throw the edit away. Remove the record yourself, then undo again "
    "to bring the session back."
)
REMOVED_ON_ITS_OWN = (
    "That session was removed on its own, after its record was, so this "
    "undo does not bring it back."
)


def statement_from_session(
    session: PlayerSession,
    provenance: HistoricalPlaytimeProvenance = (
        HistoricalPlaytimeProvenance.MANUALLY_ENTERED
    ),
) -> HistoricalPlaytimeStatement:
    """The record a session already states."""
    return HistoricalPlaytimeStatement(
        duration=session.effective_duration,
        when=TemporalValue.from_day(session.effective_day).canonical,
        provenance=provenance,
        playthrough_ids=(session.playthrough_id,),
        device_id=session.device_id,
        emulated=session.emulated,
        note=session.note,
    )


def _drift(
    context: CommandContext, session: PlayerSession, record: HistoricalPlaytime
) -> RowUnreadable:
    """Both live: a state no command admits."""
    return RowUnreadable(
        f"Session {session.pk} of library {context.library.pk} is live beside "
        f"record {record.pk} made from it, which no command admits."
    )


@dataclass(frozen=True, slots=True)
class ReclassifySessionAsHistoricalPlaytime(Command):
    """State that a session was never a sitting."""

    command_name: ClassVar[CommandName] = CommandName.PLAYERSESSION_RECLASSIFY
    #: A UUID, because Command fingerprints its fields.
    session_id: uuid.UUID
    statement: HistoricalPlaytimeStatement

    def __post_init__(self) -> None:
        object.__setattr__(self, "statement", normalized_statement(self.statement))

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        session = library_session(context, self.session_id)
        #: Resolved, not followed: the FK drops the scope.
        run = refuse_unless_live(_session_run(context, session))
        record = live_record_from(context, session)
        #: Under dispatch's lock: no mark can move.
        if session.removed_at is not None:
            if record is not None:
                raise CommandRejected(
                    f"Session {session.pk} is already record {record.pk}.",
                    sentence=ALREADY_RECORDED,
                )
            raise CommandRejected(
                f"This library removed session {session.pk}, so it states no "
                "further facts about it.",
                sentence=SESSION_REMOVED,
            )
        if record is not None:
            raise _drift(context, session, record)
        if (
            session.timing_mode == PlayerSessionTimingMode.TIMED
            and session.ended_at is None
        ):
            raise CommandRejected(
                f"Session {session.pk} is a running Timed row, so the hours it "
                "states are still moving.",
                sentence=STILL_RUNNING,
            )
        runs = _live_runs(context, self.statement)
        if runs[0].player_game_id != run.player_game_id:
            raise CommandRejected(
                f"Session {session.pk} belongs to player game "
                f"{run.player_game_id}, and the statement names playthroughs "
                f"of {runs[0].player_game_id}.",
                sentence=ANOTHER_GAME,
            )
        #: A held device stays, removed or not: a library that
        #: stopped using a device removed it, and the row must convert.
        if self.statement.device_id == session.device_id:
            device = library_device_row(context, self.statement.device_id)
        else:
            device = library_device(context, self.statement.device_id)
        created = created_event(
            runs, device, self.statement, reclassified_from=session.pk
        )
        return [
            created,
            playersession_reclassified(session.pk, record_id=created.aggregate_id),
        ]


@dataclass(frozen=True, slots=True)
class UndoSessionReclassification(Command):
    """Take back the act, both halves of it."""

    command_name: ClassVar[CommandName] = (
        CommandName.PLAYERSESSION_UNDO_RECLASSIFICATION
    )
    #: A UUID, because Command fingerprints its fields.
    session_id: uuid.UUID

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        session = library_session(context, self.session_id)
        #: The marks decide; nothing reads the history.
        records = list(
            HistoricalPlaytime.objects.filter(
                library=context.library, reclassified_from=session
            )
        )
        if not records:
            raise CommandRejected(
                f"No record of this library was made from session "
                f"{session.pk}, so there is no act to undo.",
                sentence=NEVER_RECLASSIFIED,
            )
        record = live_record_from(context, session)
        #: No-op first: a second press restores nothing.
        if record is None and session.removed_at is None:
            return Unchanged(
                f"This library already undid the reclassification of session "
                f"{self.session_id}."
            )
        if record is not None and session.removed_at is None:
            raise _drift(context, session, record)
        #: Whole: a refused leg alone would leave both live.
        if record is not None and record.restated_at is not None:
            raise CommandRejected(
                f"Record {record.pk} was restated after session {session.pk} "
                "became it, so removing it would take back more than the act.",
                sentence=RESTATED_SINCE,
            )
        #: The act marks the session before its record can be marked,
        #: so a session marked after its last record was is another act's.
        if record is None and session.removed_at is not None:
            latest = max(
                removed.removed_at for removed in records if removed.removed_at
            )
            if session.removed_at > latest:
                raise CommandRejected(
                    f"Session {session.pk} was removed at {session.removed_at}, "
                    f"after its last record was at {latest}; a plain removal "
                    "is RestoreSession's to undo.",
                    sentence=REMOVED_ON_ITS_OWN,
                )
        _refuse_under_a_removed_parent(context, session)
        if record is not None:
            _refuse_under_the_records_removed_parent(context, record)
        #: Past the refusals the session is removed; the record may be.
        events: list[NewEvent] = []
        if record is not None:
            events.append(historicalplaytime_removed(record.pk))
        events.append(playersession_restored(session.pk))
        return events
