"""Events about a device a library owns."""

import uuid
from typing import Literal, TypedDict

from pydantic import with_config

from games.events.references import STRICT_SCHEMA
from games.events.vocabulary import DEFAULT_EVENT_TYPES, EventSpec, NewEvent

#: Recorded spelling: the six values `Device.type` stores.
type DeviceTypeValue = Literal[
    "PC", "Console", "Handheld", "Mobile", "Single-board computer", "Unknown"
]


@with_config(STRICT_SCHEMA)
class DeviceCreatedPayload(TypedDict):
    """The device as first stated."""

    name: str
    type: DeviceTypeValue


@with_config(STRICT_SCHEMA)
class DeviceNameChangedPayload(TypedDict):
    """The device is called this now."""

    name: str


@with_config(STRICT_SCHEMA)
class DeviceTypeChangedPayload(TypedDict):
    """The device is of this type now."""

    type: DeviceTypeValue


@with_config(STRICT_SCHEMA)
class DeviceMarkPayload(TypedDict):
    """Removed and restored state nothing more."""


DEVICE_CREATED = EventSpec(
    "library.device.created",
    aggregate_type="device",
    payload=DeviceCreatedPayload,
)
DEVICE_NAME_CHANGED = EventSpec(
    "library.device.name_changed",
    aggregate_type="device",
    payload=DeviceNameChangedPayload,
)
DEVICE_TYPE_CHANGED = EventSpec(
    "library.device.type_changed",
    aggregate_type="device",
    payload=DeviceTypeChangedPayload,
)
DEVICE_REMOVED = EventSpec(
    "library.device.removed",
    aggregate_type="device",
    payload=DeviceMarkPayload,
)
DEVICE_RESTORED = EventSpec(
    "library.device.restored",
    aggregate_type="device",
    payload=DeviceMarkPayload,
)
for _spec in (
    DEVICE_CREATED,
    DEVICE_NAME_CHANGED,
    DEVICE_TYPE_CHANGED,
    DEVICE_REMOVED,
    DEVICE_RESTORED,
):
    DEFAULT_EVENT_TYPES.register(_spec)


def device_created(
    name: str, device_type: DeviceTypeValue, *, device_id: uuid.UUID | None = None
) -> NewEvent:
    """A new device; key minted unless given."""
    return DEVICE_CREATED.new(
        aggregate_id=uuid.uuid7() if device_id is None else device_id,
        payload={"name": name, "type": device_type},
    )


def device_name_changed(device_id: uuid.UUID, name: str) -> NewEvent:
    return DEVICE_NAME_CHANGED.new(aggregate_id=device_id, payload={"name": name})


def device_type_changed(device_id: uuid.UUID, device_type: DeviceTypeValue) -> NewEvent:
    return DEVICE_TYPE_CHANGED.new(
        aggregate_id=device_id, payload={"type": device_type}
    )


def device_removed(device_id: uuid.UUID) -> NewEvent:
    return DEVICE_REMOVED.new(aggregate_id=device_id, payload={})


def device_restored(device_id: uuid.UUID) -> NewEvent:
    return DEVICE_RESTORED.new(aggregate_id=device_id, payload={})
