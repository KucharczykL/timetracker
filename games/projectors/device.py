"""Current-state rows for owned devices."""

from typing import ClassVar

from games.events.device import (
    DEVICE_CREATED,
    DEVICE_NAME_CHANGED,
    DEVICE_REMOVED,
    DEVICE_RESTORED,
    DEVICE_TYPE_CHANGED,
)
from games.events.envelope import RecordedEvent
from games.events.projection import HandlerMap, Projector, ProjectorFamily
from games.models import Device


class Devices(Projector):
    """One row per device."""

    family_name = ProjectorFamily.CURRENT_STATE

    def _created(self, event: RecordedEvent) -> None:
        #: Never names the mark; removal survives replay.
        self.project(
            Device,
            event,
            name=event.payload["name"],
            type=event.payload["type"],
            #: The event's instant, so a replay agrees.
            created_at=event.recorded_at,
        )

    def _name_changed(self, event: RecordedEvent) -> None:
        self.amend(Device, event, name=event.payload["name"])

    def _type_changed(self, event: RecordedEvent) -> None:
        self.amend(Device, event, type=event.payload["type"])

    def _removed(self, event: RecordedEvent) -> None:
        self.amend(Device, event, removed_at=event.recorded_at)

    def _restored(self, event: RecordedEvent) -> None:
        self.amend(Device, event, removed_at=None)

    handles: ClassVar[HandlerMap] = {
        DEVICE_CREATED: _created,
        DEVICE_NAME_CHANGED: _name_changed,
        DEVICE_TYPE_CHANGED: _type_changed,
        DEVICE_REMOVED: _removed,
        DEVICE_RESTORED: _restored,
    }
