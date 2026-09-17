"""Commands about historical playtime."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import ClassVar, NamedTuple, cast

from games.commands.playersession import DURATION_RESOLUTION, check_note
from games.commands.playthrough import library_playthrough, refuse_unless_live
from games.commands.scope import Refusal, library_device, library_row
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
    HistoricalPlaytime,
    HistoricalPlaytimeProvenance,
    HistoricalPlaytimeRun,
    Playthrough,
    PlaythroughKind,
)
from games.projectors.historical_playtime import columns_for_statement
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
    duration = statement.duration - (statement.duration % DURATION_RESOLUTION)
    if duration < DURATION_RESOLUTION:
        raise CommandRejected(
            f"A historical playtime of {statement.duration} states no time.",
            sentence=AT_LEAST_A_SECOND,
        )
    try:
        when = TemporalValue.parse(statement.when).canonical
    except TemporalValueParseError as error:
        raise CommandRejected(
            f"{statement.when!r} is not a temporal value: {error}",
            sentence=str(error),
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
        HistoricalPlaytime.objects.select_related("player_game"),
        Refusal(
            message=f"This library holds no historical playtime record {record_id}.",
            sentence="That record is not available.",
        ),
        pk=record_id,
    )


def _live_record(context: CommandContext, record_id: uuid.UUID) -> HistoricalPlaytime:
    record = library_record(context, record_id)
    #: Under dispatch's lock: marks cannot move.
    if record.player_game.removed_at is not None:
        raise CommandRejected(
            f"This library removed the game behind record {record_id}.",
            sentence=(
                "That game was removed from your library. Restore it before "
                "changing this."
            ),
        )
    if record.removed_at is not None:
        raise CommandRejected(
            f"This library removed record {record_id}, so it states nothing further.",
            sentence="That record was removed. Restore it before changing it.",
        )
    return record


def _held_columns(record: HistoricalPlaytime) -> dict[str, object]:
    """The row as the projector spells it."""
    return {
        "player_game_id": record.player_game_id,
        "duration": record.duration,
        "when": None if record.when is None else record.when.canonical,
        "provenance": record.provenance,
        "device_id": record.device_id,
        "emulated": record.emulated,
        "note": record.note,
    }


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
        return [
            historicalplaytime_created(
                player_game_id=runs[0].player_game_id,
                runs=_members(runs, {}),
                duration=self.statement.duration,
                when=TemporalValue.parse(self.statement.when),
                provenance=_recorded(self.statement.provenance),
                device=None if device is None else capture_reference(device),
                emulated=self.statement.emulated,
                note=self.statement.note,
            )
        ]


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
        if dict(stated) == _held_columns(record) and same_runs:
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
        return [historicalplaytime_removed(record.pk)]


@dataclass(frozen=True, slots=True)
class RestoreHistoricalPlaytime(Command):
    """Put a removed record back."""

    command_name: ClassVar[CommandName] = CommandName.HISTORICALPLAYTIME_RESTORE
    record_id: uuid.UUID

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        record = library_record(context, self.record_id)
        if record.removed_at is None:
            return Unchanged(f"This library did not remove record {self.record_id}.")
        return [historicalplaytime_restored(record.pk)]
