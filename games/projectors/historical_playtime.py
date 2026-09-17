"""Current-state rows for historical playtime."""

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

    A TypedDict, so a dropped key is mypy's finding: `amend` would
    keep the old value in silence.
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
    """Every column, every time."""
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
    """The payload as its schema reads it."""
    return cast("HistoricalPlaytimeStatementPayload", event.payload)


class HistoricalPlaytimes(Projector):
    """One record row; one join per run."""

    family_name = ProjectorFamily.CURRENT_STATE

    def _write_runs(self, event: RecordedEvent) -> None:
        """The record's runs, replaced whole."""
        rows = self.library_rows(HistoricalPlaytimeRun, event)
        rows.filter(record_id=event.aggregate_id).delete()
        #: bulk_create ignores the filter; rows state library.
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
        #: Never names the mark; removal survives replay.
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
        #: The event's instant, so replay agrees.
        self.amend(HistoricalPlaytime, event, removed_at=event.recorded_at)

    def _restored(self, event: RecordedEvent) -> None:
        self.amend(HistoricalPlaytime, event, removed_at=None)

    handles: ClassVar[HandlerMap] = {
        HISTORICALPLAYTIME_CREATED: _created,
        HISTORICALPLAYTIME_RESTATED: _restated,
        HISTORICALPLAYTIME_REMOVED: _removed,
        HISTORICALPLAYTIME_RESTORED: _restored,
    }
