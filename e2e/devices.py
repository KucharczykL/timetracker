"""Test devices via append_command; dispatch cannot nest."""

import uuid

from django.db import transaction

from games.commands.device import CreateDevice, RemoveDevice, RestoreDevice
from games.events.dispatch import Command, CommandResult, append_command
from games.models import Device, UserLibrary
from games.reads.events import created_aggregate_id


def _state(library: UserLibrary, command: Command) -> CommandResult:
    with transaction.atomic():
        return append_command(
            command,
            actor=library.user,
            library=library,
            idempotency_key=str(uuid.uuid7()),
            correlation_id=uuid.uuid7(),
        )


def create_device(
    library: UserLibrary, name: str = "Steam Deck", type: str = Device.UNKNOWN
) -> Device:
    """A live device, created by event."""
    result = _state(library, CreateDevice(name=name, type=type))
    return Device.objects.get(pk=created_aggregate_id(result))


def remove_device(device: Device) -> Device:
    """Remove a device by event."""
    _state(device.library, RemoveDevice(device_id=device.pk))
    device.refresh_from_db()
    return device


def restore_device(device: Device) -> Device:
    """Restore a device by event."""
    _state(device.library, RestoreDevice(device_id=device.pk))
    device.refresh_from_db()
    return device
