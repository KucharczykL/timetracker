"""Commands about historical playtime."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import ClassVar, NamedTuple, cast

from games.commands.playersession import DURATION_RESOLUTION, check_note
from games.commands.playthrough import library_playthrough, refuse_unless_live
from games.commands.scope import (
    Refusal,
    library_device,
    library_device_row,
    library_row,
)
from games.events.dispatch import (
    Command,
    CommandContext,
    CommandName,
    CommandRejected,
)
from games.events.historical_playtime import (
    HistoricalPlaytimeRunPayload,
    HistoricalPlaytimeStatementPayload,
    ProvenanceValue,
    historicalplaytime_created,
    historicalplaytime_removed,
    historicalplaytime_restated,
    historicalplaytime_restored,
)
from games.events.references import capture_reference
from games.events.vocabulary import NewEvent, Unchanged
from games.models import (
    Device,
    HistoricalPlaytime,
    HistoricalPlaytimeProvenance,
    HistoricalPlaytimeRun,
    Playthrough,
    PlaythroughKind,
)
from games.projectors.historical_playtime import (
    StatementColumns,
    columns_for_statement,
)
from timetracker.temporal import TemporalValue, TemporalValueParseError

ONE_GAME = (
    "Historical playtime belongs to one game. Choose playthroughs of the same game."
)
#: The bucket is the importer's.
INTO_THE_BUCKET_HISTORICAL = (
    "That is the imported-history bucket. Record historical playtime on one of "
    "the game's playthroughs instead."
)
AT_LEAST_ONE_RUN = "Choose at least one playthrough."
AT_LEAST_A_SECOND = "Historical playtime is at least a second."
GAME_REMOVED = (
    "That game was removed from your library. Restore it before changing "
    "its historical playtime."
)
RUN_REMOVED = (
    "That playthrough was removed from your library. Restore it before "
    "changing this record."
)
RECORD_REMOVED = "That record was removed. Restore it before changing it."
#: One rule, both directions: hours stated once.
SESSION_STILL_LIVE = (
    "The session this record was made from is back in your lists, so its "
    "playtime is already counted."
)
ANOTHER_RECORD_LIVE = (
    "Another historical playtime record made from the same session is live, "
    "so its playtime is already counted."
)
WHEN_NOT_A_DATE = (
    "Write when as a year, a month or a day, like 2005, 2005-03 or 2005-03-14."
)
WHEN_NO_SUCH_DATE = "That date does not exist. Check the year, month and day."
WHEN_RANGE_BACKWARDS = "A range runs from an earlier date to a later one."
WHEN_UNSUPPORTED = (
    "That date notation is not supported. Use a year, a month, a day or a "
    "range of them."
)

#: Every parser code a person can act on, by sentence.
_WHEN_SENTENCES: dict[str, str] = {
    "invalid_syntax": WHEN_NOT_A_DATE,
    "invalid_number": WHEN_NOT_A_DATE,
    "invalid_kind": WHEN_NOT_A_DATE,
    "unread_parts": WHEN_NOT_A_DATE,
    "invalid_date": WHEN_NO_SUCH_DATE,
    "invalid_year": WHEN_NO_SUCH_DATE,
    "invalid_decade": WHEN_NO_SUCH_DATE,
    "incomplete_day": WHEN_NO_SUCH_DATE,
    "incomplete_month": WHEN_NO_SUCH_DATE,
    "decade_with_year": WHEN_NO_SUCH_DATE,
    "invalid_range": WHEN_RANGE_BACKWARDS,
}


def when_sentence(error: TemporalValueParseError) -> str:
    """A written sentence for a parser code."""
    return _WHEN_SENTENCES.get(error.code, WHEN_UNSUPPORTED)


class HistoricalPlaytimeStatement(NamedTuple):
    """One record, as a person states it."""

    duration: timedelta
    #: Canonical temporal text; None is unknown.
    when: str | None
    provenance: HistoricalPlaytimeProvenance
    playthrough_ids: tuple[uuid.UUID, ...]
    device_id: uuid.UUID | None
    emulated: bool
    note: str


def normalized_statement(
    statement: HistoricalPlaytimeStatement,
) -> HistoricalPlaytimeStatement:
    """One spelling; refusals first."""
    note = statement.note.strip()
    check_note(note)
    runs = tuple(sorted(set(statement.playthrough_ids), key=str))
    if not runs:
        raise CommandRejected(
            "A historical playtime statement names no playthrough.",
            sentence=AT_LEAST_ONE_RUN,
        )
    #: Truncated, not refused: clocks and imports feed this.
    duration = statement.duration - (statement.duration % DURATION_RESOLUTION)
    if duration < DURATION_RESOLUTION:
        raise CommandRejected(
            f"A historical playtime of {statement.duration} states no time.",
            sentence=AT_LEAST_A_SECOND,
        )
    try:
        when = TemporalValue.parse(statement.when).canonical
    except TemporalValueParseError as error:
        #: A wrong type is the caller's defect, not a refusal.
        if error.code == "invalid_type":
            raise
        raise CommandRejected(
            f"{statement.when!r} is not a temporal value: {error}",
            sentence=when_sentence(error),
        ) from None
    return statement._replace(
        note=note, playthrough_ids=runs, duration=duration, when=when
    )


def _live_runs(
    context: CommandContext, statement: HistoricalPlaytimeStatement
) -> list[Playthrough]:
    """Every run live, one game, no bucket."""
    runs = [
        refuse_unless_live(library_playthrough(context, run_id))
        for run_id in statement.playthrough_ids
    ]
    if len({run.player_game_id for run in runs}) != 1:
        raise CommandRejected(
            "A historical playtime statement names playthroughs of two games.",
            sentence=ONE_GAME,
        )
    for run in runs:
        if run.kind == PlaythroughKind.IMPORTED_HISTORY:
            raise CommandRejected(
                f"Playthrough {run.pk} is the imported-history bucket, which "
                "takes no stated playtime.",
                sentence=INTO_THE_BUCKET_HISTORICAL,
            )
    return runs


def _recorded(provenance: HistoricalPlaytimeProvenance) -> ProvenanceValue:
    """The choice as the payload spells it."""
    return cast("ProvenanceValue", provenance.value)


def _members(
    runs: Sequence[Playthrough], kept: dict[uuid.UUID, uuid.UUID]
) -> list[HistoricalPlaytimeRunPayload]:
    """Join id per run: kept or fresh."""
    return [
        {"id": str(kept.get(run.pk, uuid.uuid7())), "playthrough": str(run.pk)}
        for run in runs
    ]


def library_record(context: CommandContext, record_id: uuid.UUID) -> HistoricalPlaytime:
    """This library's record, removed or not."""
    return library_row(
        context,
        HistoricalPlaytime.objects.select_related("player_game", "reclassified_from"),
        Refusal(
            message=f"This library holds no historical playtime record {record_id}.",
            sentence="That record is not available.",
        ),
        pk=record_id,
    )


def _refuse_under_a_removed_parent(
    context: CommandContext, record: HistoricalPlaytime
) -> None:
    """Refuse an act under a removed game or run."""
    #: Under dispatch's lock: marks cannot move.
    if record.player_game.removed_at is not None:
        raise CommandRejected(
            f"This library removed the game behind record {record.pk}, so its "
            "historical playtime neither leaves the totals nor comes back.",
            sentence=GAME_REMOVED,
        )
    removed_runs = HistoricalPlaytimeRun.objects.filter(
        record=record, library=context.library, playthrough__removed_at__isnull=False
    )
    if removed_runs.exists():
        raise CommandRejected(
            f"This library removed a playthrough record {record.pk} names, so "
            "the record neither leaves the totals nor comes back.",
            sentence=RUN_REMOVED,
        )


def _live_record(context: CommandContext, record_id: uuid.UUID) -> HistoricalPlaytime:
    record = library_record(context, record_id)
    _refuse_under_a_removed_parent(context, record)
    if record.removed_at is not None:
        raise CommandRejected(
            f"This library removed record {record_id}, so it states nothing further.",
            sentence=RECORD_REMOVED,
        )
    return record


def _held_columns(record: HistoricalPlaytime) -> StatementColumns:
    """The row as the projector spells it."""
    return {
        "player_game_id": record.player_game_id,
        "duration": record.duration,
        "when": None if record.when is None else record.when.canonical,
        "provenance": HistoricalPlaytimeProvenance(record.provenance),
        "device_id": record.device_id,
        "emulated": record.emulated,
        "note": record.note,
    }


def created_event(
    runs: Sequence[Playthrough],
    device: Device | None,
    statement: HistoricalPlaytimeStatement,
    *,
    reclassified_from: uuid.UUID | None = None,
) -> NewEvent:
    """One statement as the creation event; caller resolves both."""
    return historicalplaytime_created(
        player_game_id=runs[0].player_game_id,
        runs=_members(runs, {}),
        duration=statement.duration,
        when=TemporalValue.parse(statement.when),
        provenance=_recorded(statement.provenance),
        device=None if device is None else capture_reference(device),
        emulated=statement.emulated,
        note=statement.note,
        reclassified_from=reclassified_from,
    )


@dataclass(frozen=True, slots=True)
class RecordHistoricalPlaytime(Command):
    """State untracked playtime."""

    command_name: ClassVar[CommandName] = CommandName.HISTORICALPLAYTIME_RECORD
    statement: HistoricalPlaytimeStatement

    def __post_init__(self) -> None:
        object.__setattr__(self, "statement", normalized_statement(self.statement))

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        runs = _live_runs(context, self.statement)
        device = library_device(context, self.statement.device_id)
        return [created_event(runs, device, self.statement)]


@dataclass(frozen=True, slots=True)
class RestateHistoricalPlaytime(Command):
    """State the whole record again."""

    command_name: ClassVar[CommandName] = CommandName.HISTORICALPLAYTIME_RESTATE
    record_id: uuid.UUID
    statement: HistoricalPlaytimeStatement

    def __post_init__(self) -> None:
        object.__setattr__(self, "statement", normalized_statement(self.statement))

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        record = _live_record(context, self.record_id)
        runs = _live_runs(context, self.statement)
        #: A held device is kept, removed or not; a new one must be live.
        if self.statement.device_id == record.device_id:
            device = library_device_row(context, self.statement.device_id)
        else:
            device = library_device(context, self.statement.device_id)
        #: Read under dispatch's lock; rows cannot move.
        kept = dict(
            HistoricalPlaytimeRun.objects.filter(
                record=record, library=context.library
            ).values_list("playthrough_id", "id")
        )
        event = historicalplaytime_restated(
            record.pk,
            player_game_id=runs[0].player_game_id,
            runs=_members(runs, kept),
            duration=self.statement.duration,
            when=TemporalValue.parse(self.statement.when),
            provenance=_recorded(self.statement.provenance),
            device=None if device is None else capture_reference(device),
            emulated=self.statement.emulated,
            note=self.statement.note,
        )
        #: The projector's mapping, never a copy.
        stated = columns_for_statement(
            cast("HistoricalPlaytimeStatementPayload", event.payload),
            event.effective_time,
        )
        same_runs = set(kept) == {run.pk for run in runs}
        if stated == _held_columns(record) and same_runs:
            return Unchanged("This record already states that.")
        return [event]


@dataclass(frozen=True, slots=True)
class RemoveHistoricalPlaytime(Command):
    """Take a record out of totals."""

    command_name: ClassVar[CommandName] = CommandName.HISTORICALPLAYTIME_REMOVE
    record_id: uuid.UUID

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        record = library_record(context, self.record_id)
        #: No-op first; a repeat succeeds.
        if record.removed_at is not None:
            return Unchanged(f"This library already removed record {self.record_id}.")
        _refuse_under_a_removed_parent(context, record)
        return [historicalplaytime_removed(record.pk)]


def _refuse_beside_a_live_session(
    context: CommandContext, record: HistoricalPlaytime
) -> None:
    """The mirror of the session's own guard."""
    session = record.reclassified_from
    if session is None:
        return
    #: Under dispatch's lock: no mark can move.
    if session.removed_at is None:
        raise CommandRejected(
            f"Session {session.pk} became record {record.pk} and is live again, "
            "so restoring the record would count its hours twice.",
            sentence=SESSION_STILL_LIVE,
        )
    #: A session converted twice left two records.
    sibling = (
        HistoricalPlaytime.objects.filter(
            library=context.library,
            reclassified_from=session,
            removed_at__isnull=True,
        )
        .exclude(pk=record.pk)
        .first()
    )
    if sibling is not None:
        raise CommandRejected(
            f"Record {sibling.pk} was made from session {session.pk} as well "
            f"and is live, so restoring record {record.pk} would count its "
            "hours twice.",
            sentence=ANOTHER_RECORD_LIVE,
        )


@dataclass(frozen=True, slots=True)
class RestoreHistoricalPlaytime(Command):
    """Put a removed record back."""

    command_name: ClassVar[CommandName] = CommandName.HISTORICALPLAYTIME_RESTORE
    record_id: uuid.UUID

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        record = library_record(context, self.record_id)
        if record.removed_at is None:
            return Unchanged(f"This library did not remove record {self.record_id}.")
        _refuse_under_a_removed_parent(context, record)
        _refuse_beside_a_live_session(context, record)
        return [historicalplaytime_restored(record.pk)]
