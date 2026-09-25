"""Commands about a device a library owns."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar, cast, get_args

from games.commands.scope import library_device, library_device_row
from games.events.device import (
    DeviceTypeValue,
    device_created,
    device_name_changed,
    device_removed,
    device_restored,
    device_type_changed,
)
from games.events.dispatch import (
    Command,
    CommandContext,
    CommandName,
    CommandRejected,
)
from games.events.vocabulary import NewEvent, Unchanged
from games.models import Device

#: Longer names do not fit the column.
NAME_MAX_LENGTH = cast(int, Device._meta.get_field("name").max_length)

NAME_REQUIRED = "Give the device a name."
NAME_TOO_LONG = f"A device's name is at most {NAME_MAX_LENGTH} characters."
UNKNOWN_TYPE = "Choose one of the listed device types."


def check_name(name: str) -> None:
    """Refuse a name no row should hold."""
    if not name:
        raise CommandRejected("A device states a name.", sentence=NAME_REQUIRED)
    if len(name) > NAME_MAX_LENGTH:
        raise CommandRejected(
            f"A device name of {len(name)} characters exceeds the column's "
            f"{NAME_MAX_LENGTH}.",
            sentence=NAME_TOO_LONG,
        )


def check_type(device_type: str) -> DeviceTypeValue:
    """The payload's type, or a refusal."""
    if device_type not in get_args(DeviceTypeValue.__value__):
        raise CommandRejected(
            f"{device_type!r} is not a device type.", sentence=UNKNOWN_TYPE
        )
    return cast(DeviceTypeValue, device_type)


@dataclass(frozen=True, slots=True)
class CreateDevice(Command):
    """State a device the library owns."""

    command_name: ClassVar[CommandName] = CommandName.DEVICE_CREATE
    name: str
    type: str

    def __post_init__(self) -> None:
        #: One spelling, so restatements fingerprint alike.
        object.__setattr__(self, "name", self.name.strip())

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        check_name(self.name)
        return [device_created(self.name, check_type(self.type))]


@dataclass(frozen=True, slots=True)
class DescribeDevice(Command):
    """State name, type, or both."""

    command_name: ClassVar[CommandName] = CommandName.DEVICE_DESCRIBE
    device_id: uuid.UUID
    name: str | None = None
    type: str | None = None

    def __post_init__(self) -> None:
        if self.name is not None:
            object.__setattr__(self, "name", self.name.strip())

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        if self.name is not None:
            check_name(self.name)
        stated_type = None if self.type is None else check_type(self.type)
        device = cast(Device, library_device(context, self.device_id))
        events: list[NewEvent] = []
        if self.name is not None and self.name != device.name:
            events.append(device_name_changed(device.pk, self.name))
        if stated_type is not None and stated_type != device.type:
            events.append(device_type_changed(device.pk, stated_type))
        if not events:
            return Unchanged("This device already states that.")
        return events


@dataclass(frozen=True, slots=True)
class RemoveDevice(Command):
    """Remove a device; references stay."""

    command_name: ClassVar[CommandName] = CommandName.DEVICE_REMOVE
    device_id: uuid.UUID

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        device = cast(Device, library_device_row(context, self.device_id))
        #: No-op first; a repeat succeeds.
        if device.removed_at is not None:
            return Unchanged(f"This library already removed device {device.pk}.")
        return [device_removed(device.pk)]


@dataclass(frozen=True, slots=True)
class RestoreDevice(Command):
    """Put a removed device back."""

    command_name: ClassVar[CommandName] = CommandName.DEVICE_RESTORE
    device_id: uuid.UUID

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        device = cast(Device, library_device_row(context, self.device_id))
        if device.removed_at is None:
            return Unchanged(f"Device {device.pk} is already in this library.")
        return [device_restored(device.pk)]
