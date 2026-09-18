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
from games.commands.playersession import _live_session, library_session
from games.commands.scope import library_device, library_device_row
from games.events.dispatch import (
    Command,
    CommandContext,
    CommandName,
    CommandRejected,
)
from games.events.historical_playtime import historicalplaytime_removed
from games.events.playersession import (
    playersession_reclassified,
    playersession_restored,
)
from games.events.vocabulary import NewEvent, Unchanged
from games.models import (
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
NEVER_RECLASSIFIED = (
    "That session was never recorded as historical playtime, so there is "
    "nothing to undo."
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
        session = _live_session(context, self.session_id)
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
        if runs[0].player_game_id != session.playthrough.player_game_id:
            raise CommandRejected(
                f"Session {session.pk} belongs to player game "
                f"{session.playthrough.player_game_id}, and the statement names "
                f"playthroughs of {runs[0].player_game_id}.",
                sentence=ANOTHER_GAME,
            )
        #: A held device stays, removed or not.
        #: Not library_device: a library that stopped using a device
        #: removed it, and 91 of the 93 rows this act exists for name
        #: one, so the live-only resolver refuses almost all of them.
        if self.statement.device_id == session.device_id:
            device = library_device_row(context, self.statement.device_id)
        else:
            device = library_device(context, self.statement.device_id)
        created = created_event(runs, device, self.statement)
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
        record = session.reclassified_into
        if record is None:
            raise CommandRejected(
                f"Session {session.pk} states no record, so no act of this "
                "library made it one.",
                sentence=NEVER_RECLASSIFIED,
            )
        #: No-op first: a second press restores nothing.
        if session.removed_at is None and record.removed_at is not None:
            return Unchanged(
                f"This library already undid the reclassification of session "
                f"{self.session_id}."
            )
        events: list[NewEvent] = []
        #: Each leg only where still to happen.
        if record.removed_at is None:
            events.append(historicalplaytime_removed(record.pk))
        if session.removed_at is not None:
            events.append(playersession_restored(session.pk))
        return events
