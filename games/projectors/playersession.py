"""Current-state rows for the sessions a library records."""

import uuid
from datetime import date, datetime, timedelta
from typing import ClassVar, TypedDict

from games.events.envelope import RecordedEvent
from games.events.playersession import (
    PLAYERSESSION_CREATED,
    PLAYERSESSION_DEVICE_CHANGED,
    PLAYERSESSION_EMULATED_CHANGED,
    PLAYERSESSION_ENDED,
    PLAYERSESSION_MOVED,
    PLAYERSESSION_NOTE_CHANGED,
    PLAYERSESSION_TIMING_CORRECTED,
    TimingPayload,
    day_from_text,
    instant_from_text,
)
from games.events.projection import HandlerMap, Projector, ProjectorFamily
from games.models import PlayerSession, PlayerSessionTimingMode


class TimingColumns(TypedDict):
    """The eight columns one timing statement decides.

    A TypedDict rather than a bare mapping: the contract this
    module exists to keep is that all eight are named every time,
    and a dropped key would otherwise be found by `project()` at
    append time rather than by the type checker.
    """

    timing_mode: PlayerSessionTimingMode
    started_at: datetime | None
    started_at_zone: str | None
    ended_at: datetime | None
    ended_at_zone: str | None
    stated_day: date | None
    stated_duration: timedelta | None
    day_zone: str | None


def columns_for_timing(timing: TimingPayload) -> TimingColumns:
    """The eight columns one timing statement decides.

    Every one of them, every time: a column the mode forbids is named
    as None rather than left out. A correction that states another
    mode amends the row, and `amend` writes only the columns it is
    handed, so anything unnamed would keep the value the old mode put
    there.
    """
    columns: TimingColumns = {
        "timing_mode": PlayerSessionTimingMode(timing["mode"]),
        "started_at": None,
        "started_at_zone": None,
        "ended_at": None,
        "ended_at_zone": None,
        "stated_day": None,
        "stated_duration": None,
        "day_zone": None,
    }
    if timing["mode"] == "duration_only":
        columns["stated_day"] = day_from_text(timing["stated_day"])
        columns["stated_duration"] = timedelta(seconds=timing["duration_seconds"])
        return columns
    columns["started_at"] = instant_from_text(timing["started_at"])
    columns["started_at_zone"] = timing["started_at_zone"]
    columns["ended_at_zone"] = timing["ended_at_zone"]
    columns["day_zone"] = timing["day_zone"]
    if timing["mode"] == "corrected":
        columns["ended_at"] = instant_from_text(timing["ended_at"])
        columns["stated_duration"] = timedelta(seconds=timing["duration_seconds"])
        return columns
    ended_at = timing["ended_at"]
    columns["ended_at"] = None if ended_at is None else instant_from_text(ended_at)
    return columns


class PlayerSessions(Projector):
    """One row per session a library recorded."""

    family_name = ProjectorFamily.CURRENT_STATE

    def _created(self, event: RecordedEvent) -> None:
        payload = event.payload
        device = payload["device"]
        self.project(
            PlayerSession,
            event.aggregate_id,
            #: From the event, never a command's context.
            library_id=event.library_id,
            playthrough_id=uuid.UUID(payload["playthrough"]),
            device_id=None if device is None else uuid.UUID(device["id"]),
            note=payload["note"],
            emulated=payload["emulated"],
            created_at=event.recorded_at,
            **columns_for_timing(payload["timing"]),
        )

    def _ended(self, event: RecordedEvent) -> None:
        """Two columns; earlier statements wrote the rest."""
        payload = event.payload
        self.amend(
            PlayerSession,
            event.aggregate_id,
            ended_at=instant_from_text(payload["ended_at"]),
            ended_at_zone=payload["ended_at_zone"],
        )

    def _timing_corrected(self, event: RecordedEvent) -> None:
        """All eight columns; no old mode stays."""
        self.amend(
            PlayerSession,
            event.aggregate_id,
            **columns_for_timing(event.payload["timing"]),
        )

    def _note_changed(self, event: RecordedEvent) -> None:
        self.amend(PlayerSession, event.aggregate_id, note=event.payload["note"])

    def _device_changed(self, event: RecordedEvent) -> None:
        device = event.payload["device"]
        self.amend(
            PlayerSession,
            event.aggregate_id,
            device_id=None if device is None else uuid.UUID(device["id"]),
        )

    def _emulated_changed(self, event: RecordedEvent) -> None:
        self.amend(
            PlayerSession, event.aggregate_id, emulated=event.payload["emulated"]
        )

    def _moved(self, event: RecordedEvent) -> None:
        self.amend(
            PlayerSession,
            event.aggregate_id,
            playthrough_id=uuid.UUID(event.payload["playthrough"]),
        )

    handles: ClassVar[HandlerMap] = {
        PLAYERSESSION_CREATED: _created,
        PLAYERSESSION_ENDED: _ended,
        PLAYERSESSION_TIMING_CORRECTED: _timing_corrected,
        PLAYERSESSION_NOTE_CHANGED: _note_changed,
        PLAYERSESSION_DEVICE_CHANGED: _device_changed,
        PLAYERSESSION_EMULATED_CHANGED: _emulated_changed,
        PLAYERSESSION_MOVED: _moved,
    }
