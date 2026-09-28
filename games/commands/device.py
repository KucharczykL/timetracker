"""Commands about a device a library owns."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from functools import partial
from typing import ClassVar, cast, get_args

from games.commands.endpoint import (
    EndpointSentences,
    Rejection,
    WayActStatement,
    correct_endpoint,
    state_endpoint,
    void_endpoint,
)
from games.commands.scope import library_device, library_device_row
from games.end_ways import EndWay
from games.endpoints import DEVICE_ACCESS_END
from games.events.device import (
    DeviceTypeValue,
    DeviceWayValue,
    device_access_ended,
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
from games.models import DEVICE_WAYS, Device
from timetracker.temporal import stated_date

#: Longer names do not fit the column.
NAME_MAX_LENGTH = cast(int, Device._meta.get_field("name").max_length)

NAME_REQUIRED = "Give the device a name."
NAME_TOO_LONG = f"A device's name is at most {NAME_MAX_LENGTH} characters."
UNKNOWN_TYPE = "Choose one of the listed device types."
UNKNOWN_WAY = "Choose one of the listed ways a device leaves your hands."


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


def check_way(way: str) -> EndWay:
    """The device way stated, or a refusal.

    Ahead of the payload's own validation, which would answer
    a way outside the device's with a defect, not a sentence.
    """
    if way not in DEVICE_WAYS:
        raise CommandRejected(
            f"{way!r} is not a way a device's access ends.", sentence=UNKNOWN_WAY
        )
    return EndWay(way)


def normalized(statement: WayActStatement) -> WayActStatement:
    """One spelling of no day and no note, so restatements fingerprint alike."""
    return WayActStatement(
        stated_date(statement.when), statement.way, statement.note.strip()
    )


def _access_end_sentences(device_id: uuid.UUID) -> EndpointSentences:
    return EndpointSentences(
        already_stated=Rejection(
            f"Device {device_id} already states an end of access. "
            "CorrectDeviceAccessEnd states a better one.",
            "This device already has an end recorded. Correct the one it has "
            "instead of adding another.",
        ),
        nothing_to_correct=Rejection(
            f"Device {device_id} states no end of access, so there is nothing "
            "to correct. A first statement is EndDeviceAccess.",
            "This device has no end to correct. Record how it left first.",
        ),
        same_statement="This device already states that end.",
        same_correction="This correction states the end the device states.",
        nothing_to_void=f"Device {device_id} states no end of access to take back.",
    )


def _refuse_a_removed_device(device: Device) -> None:
    #: Under dispatch's lock; the mark cannot move.
    if device.removed_at is not None:
        raise CommandRejected(
            f"This library removed device {device.pk}, so it states no further "
            "facts about it.",
            sentence=(
                "That device was removed. Put it back before changing what it records."
            ),
        )


def _held_device(context: CommandContext, device_id: uuid.UUID) -> Device:
    device = cast(Device, library_device_row(context, device_id))
    _refuse_a_removed_device(device)
    return device


@dataclass(frozen=True, slots=True)
class CreateDevice(Command):
    """State a device the library owns."""

    command_name: ClassVar[CommandName] = CommandName.DEVICE_CREATE
    name: str
    type: str
    #: A device recorded after the library parted with it.
    access_end: WayActStatement | None = None

    def __post_init__(self) -> None:
        #: One spelling, so restatements fingerprint alike.
        object.__setattr__(self, "name", self.name.strip())
        if self.access_end is not None:
            object.__setattr__(self, "access_end", normalized(self.access_end))

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        check_name(self.name)
        device_type = check_type(self.type)
        if self.access_end is None:
            return [device_created(self.name, device_type)]
        way = check_way(self.access_end.way)
        device_id = uuid.uuid7()
        return [
            device_created(self.name, device_type, device_id=device_id),
            device_access_ended(
                device_id,
                when=self.access_end.when,
                way=cast(DeviceWayValue, way.value),
                note=self.access_end.note,
            ),
        ]


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


@dataclass(frozen=True, slots=True)
class EndDeviceAccess(Command):
    """State that the library's access to a device ended."""

    command_name: ClassVar[CommandName] = CommandName.DEVICE_END_ACCESS
    device_id: uuid.UUID
    statement: WayActStatement

    def __post_init__(self) -> None:
        object.__setattr__(self, "statement", normalized(self.statement))

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        way = check_way(self.statement.way)
        device = _held_device(context, self.device_id)
        return state_endpoint(
            device,
            DEVICE_ACCESS_END,
            when=self.statement.when,
            note=self.statement.note,
            way=way,
            sentences=_access_end_sentences(device.pk),
        )


@dataclass(frozen=True, slots=True)
class CorrectDeviceAccessEnd(Command):
    """State a better day, way or note for an end already stated."""

    command_name: ClassVar[CommandName] = CommandName.DEVICE_CORRECT_ACCESS_END
    device_id: uuid.UUID
    statement: WayActStatement

    def __post_init__(self) -> None:
        object.__setattr__(self, "statement", normalized(self.statement))

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        way = check_way(self.statement.way)
        device = _held_device(context, self.device_id)
        return correct_endpoint(
            device,
            DEVICE_ACCESS_END,
            when=self.statement.when,
            note=self.statement.note,
            way=way,
            sentences=_access_end_sentences(device.pk),
        )


@dataclass(frozen=True, slots=True)
class VoidDeviceAccessEnd(Command):
    """Take back the record that the library's access ended."""

    command_name: ClassVar[CommandName] = CommandName.DEVICE_VOID_ACCESS_END
    device_id: uuid.UUID

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        device = cast(Device, library_device_row(context, self.device_id))
        return void_endpoint(
            device,
            DEVICE_ACCESS_END,
            sentences=_access_end_sentences(device.pk),
            before_event=partial(_refuse_a_removed_device, device),
        )
