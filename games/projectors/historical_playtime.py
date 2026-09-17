"""Current-state rows for the playtime a library states without sittings."""

import uuid
from datetime import timedelta
from typing import ClassVar, TypedDict, cast

from games.events.envelope import RecordedEvent
from games.events.historical_playtime import (
    HISTORICALPLAYTIME_CREATED,
    HISTORICALPLAYTIME_REMOVED,
    HISTORICALPLAYTIME_RESTATED,
    HISTORICALPLAYTIME_RESTORED,
    HistoricalPlaytimeStatementPayload,
)
from games.events.projection import HandlerMap, Projector, ProjectorFamily
from games.models import (
    HistoricalPlaytime,
    HistoricalPlaytimeProvenance,
    HistoricalPlaytimeRun,
)
from timetracker.temporal import TemporalValue


class StatementColumns(TypedDict):
    """The seven columns one statement decides.

    A TypedDict so a dropped key is the type checker's finding, not
    `project()`'s at append time.
    """

    player_game_id: uuid.UUID
    duration: timedelta
    when: str | None
    provenance: HistoricalPlaytimeProvenance
    device_id: uuid.UUID | None
    emulated: bool
    note: str


def columns_for_statement(
    payload: HistoricalPlaytimeStatementPayload, effective_time: TemporalValue | None
) -> StatementColumns:
    """Every column, every time: a restatement overwrites the whole row."""
    device = payload["device"]
    return {
        "player_game_id": uuid.UUID(payload["player_game"]),
        "duration": timedelta(seconds=payload["duration_seconds"]),
        "when": None if effective_time is None else effective_time.canonical,
        "provenance": HistoricalPlaytimeProvenance(payload["provenance"]),
        "device_id": None if device is None else uuid.UUID(device["id"]),
        "emulated": payload["emulated"],
        "note": payload["note"],
    }


def _statement_of(event: RecordedEvent) -> HistoricalPlaytimeStatementPayload:
    """The payload as its schema reads it; validated at append."""
    return cast("HistoricalPlaytimeStatementPayload", event.payload)


class HistoricalPlaytimes(Projector):
    """One row per record, and one join row per run it names."""

    family_name = ProjectorFamily.CURRENT_STATE

    def _write_runs(self, event: RecordedEvent) -> None:
        """The record's runs, replaced whole.

        A derived set is never patched: this record's rows in the
        event's library are taken out and written again from the
        payload, each with the id the statement carries, so a kept run
        keeps its row and a replay reproduces every id.
        """
        rows = self.library_rows(HistoricalPlaytimeRun, event)
        rows.filter(record_id=event.aggregate_id).delete()
        #: `bulk_create` reads no filter; each row states its library.
        rows.bulk_create(
            [
                rows.model(
                    id=uuid.UUID(member["id"]),
                    library_id=event.library_id,
                    record_id=event.aggregate_id,
                    playthrough_id=uuid.UUID(member["playthrough"]),
                )
                for member in event.payload["playthroughs"]
            ]
        )

    def _created(self, event: RecordedEvent) -> None:
        #: Never names the mark, so a removal survives a replayed restate.
        self.project(
            HistoricalPlaytime,
            event,
            created_at=event.recorded_at,
            **columns_for_statement(_statement_of(event), event.effective_time),
        )
        self._write_runs(event)

    def _restated(self, event: RecordedEvent) -> None:
        self.amend(
            HistoricalPlaytime,
            event,
            **columns_for_statement(_statement_of(event), event.effective_time),
        )
        self._write_runs(event)

    def _removed(self, event: RecordedEvent) -> None:
        #: The event's instant, so a replay agrees.
        self.amend(HistoricalPlaytime, event, removed_at=event.recorded_at)

    def _restored(self, event: RecordedEvent) -> None:
        self.amend(HistoricalPlaytime, event, removed_at=None)

    handles: ClassVar[HandlerMap] = {
        HISTORICALPLAYTIME_CREATED: _created,
        HISTORICALPLAYTIME_RESTATED: _restated,
        HISTORICALPLAYTIME_REMOVED: _removed,
        HISTORICALPLAYTIME_RESTORED: _restored,
    }
