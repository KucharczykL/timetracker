"""Events about a device a library owns."""

import uuid
from typing import Literal, TypedDict

from pydantic import with_config

from games.events.endpoint import endpoint_events
from games.events.references import STRICT_SCHEMA
from games.events.vocabulary import DEFAULT_EVENT_TYPES, EventSpec, NewEvent
from timetracker.temporal import TemporalValue

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


#: Recorded spelling of the ways a device's access ends. A bare
#: Literal: the vocabulary stays this module's, whatever EndWay adds.
type DeviceWayValue = Literal["sold", "lost", "given_away", "broken", "stolen"]


@with_config(STRICT_SCHEMA)
class DeviceAccessEndPayload(TypedDict):
    """How the library's access to the device ended, and its note.

    The day is `effective_time`. No note is the empty string.
    """

    way: DeviceWayValue
    note: str


@with_config(STRICT_SCHEMA)
class DeviceAccessEndVoidedPayload(TypedDict):
    """The library takes back the record of an end."""


DEVICE_ACCESS_END_EVENTS = endpoint_events(
    "device",
    stated="library.device.access_ended",
    corrected="library.device.access_end_corrected",
    voided="library.device.access_end_voided",
    payload=DeviceAccessEndPayload,
    voided_payload=DeviceAccessEndVoidedPayload,
)
DEVICE_ACCESS_ENDED = DEVICE_ACCESS_END_EVENTS.stated
DEVICE_ACCESS_END_CORRECTED = DEVICE_ACCESS_END_EVENTS.corrected
DEVICE_ACCESS_END_VOIDED = DEVICE_ACCESS_END_EVENTS.voided


def device_access_ended(
    device_id: uuid.UUID,
    *,
    when: TemporalValue | None,
    way: DeviceWayValue,
    note: str,
) -> NewEvent:
    """The library's access to the device ended."""
    return DEVICE_ACCESS_ENDED.new(
        aggregate_id=device_id,
        effective_time=when,
        payload={"way": way, "note": note},
    )
