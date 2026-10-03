"""Current-state rows for historical playtime."""

import uuid
from datetime import timedelta
from typing import ClassVar, TypedDict, cast

from games.events.envelope import RecordedEvent
from games.events.historical_playtime import (
    HISTORICALPLAYTIME_CREATED,
    HISTORICALPLAYTIME_MOVED,
    HISTORICALPLAYTIME_REMOVED,
    HISTORICALPLAYTIME_RESTATED,
    HISTORICALPLAYTIME_RESTORED,
    HistoricalPlaytimeCreatedPayload,
    HistoricalPlaytimeMovedPayload,
    HistoricalPlaytimeStatementPayload,
)
from games.events.projection import HandlerMap, Projector, ProjectorFamily
from games.events.references import referenced_id
from games.models import (
    HistoricalPlaytime,
    HistoricalPlaytimeProvenance,
    HistoricalPlaytimeRun,
)
from timetracker.temporal import TemporalValue


class StatementColumns(TypedDict):
    """The eight columns one statement decides.

    A TypedDict, so a dropped key is mypy's finding: `amend` would
    keep the old value in silence.
    """

    player_game_id: uuid.UUID
    duration: timedelta
    when: str | None
    provenance: HistoricalPlaytimeProvenance
    device_id: uuid.UUID | None
    release_id: uuid.UUID | None
    emulated: bool
    note: str


def columns_for_statement(
    payload: HistoricalPlaytimeStatementPayload, effective_time: TemporalValue | None
) -> StatementColumns:
    """Every column, every time."""
    return {
        "player_game_id": uuid.UUID(payload["player_game"]),
        "duration": timedelta(seconds=payload["duration_seconds"]),
        "when": None if effective_time is None else effective_time.canonical,
        "provenance": HistoricalPlaytimeProvenance(payload["provenance"]),
        "device_id": referenced_id(payload["device"]),
        "release_id": referenced_id(payload["release"]),
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
                for member in _statement_of(event)["playthroughs"]
            ]
        )

    def _created(self, event: RecordedEvent) -> None:
        #: Never names the mark; removal survives replay.
        payload = cast("HistoricalPlaytimeCreatedPayload", event.payload)
        session = payload.get("reclassified_from")
        self.project(
            HistoricalPlaytime,
            event,
            created_at=event.recorded_at,
            reclassified_from_id=None if session is None else uuid.UUID(session),
            **columns_for_statement(payload, event.effective_time),
        )
        self._write_runs(event)

    def _restated(self, event: RecordedEvent) -> None:
        self.amend(
            HistoricalPlaytime,
            event,
            #: The event's instant, so a replay agrees.
            restated_at=event.recorded_at,
            **columns_for_statement(_statement_of(event), event.effective_time),
        )
        self._write_runs(event)

    def _removed(self, event: RecordedEvent) -> None:
        #: The event's instant, so replay agrees.
        self.amend(HistoricalPlaytime, event, removed_at=event.recorded_at)

    def _restored(self, event: RecordedEvent) -> None:
        self.amend(HistoricalPlaytime, event, removed_at=None)

    def _moved(self, event: RecordedEvent) -> None:
        #: No restated_at: nothing was restated.
        #: A re-applied creation reverts the game.
        payload = cast("HistoricalPlaytimeMovedPayload", event.payload)
        cleared = {"release_id": None} if "release" in payload else {}
        self.amend(
            HistoricalPlaytime,
            event,
            player_game_id=uuid.UUID(payload["player_game"]),
            **cleared,
        )

    handles: ClassVar[HandlerMap] = {
        HISTORICALPLAYTIME_CREATED: _created,
        HISTORICALPLAYTIME_RESTATED: _restated,
        HISTORICALPLAYTIME_REMOVED: _removed,
        HISTORICALPLAYTIME_RESTORED: _restored,
        HISTORICALPLAYTIME_MOVED: _moved,
    }
