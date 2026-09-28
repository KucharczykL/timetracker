"""Device writes; refusals become answers."""

import uuid
from typing import assert_never

from django.contrib.auth.models import User

from games.commands.device import (
    CorrectDeviceAccessEnd,
    CreateDevice,
    DescribeDevice,
    EndDeviceAccess,
    RemoveDevice,
    RestoreDevice,
    VoidDeviceAccessEnd,
)
from games.commands.endpoint import WayActStatement
from games.endpoints import DEVICE_ACCESS_END
from games.events.append import SourceMetadata
from games.events.dispatch import Command, CommandResult, dispatch
from games.events.idempotency import IdempotencyKey
from games.models import Device
from games.reads.endpoints import stated
from games.reads.events import created_aggregate_id
from games.writes.answers import SubjectNoun, answered
from games.writes.endpoint import Act, Correct, Nothing, Void, endpoint_move

SUBJECT: SubjectNoun = "device"


def _dispatch(
    command: Command,
    *,
    actor: User,
    correlation_id: uuid.UUID,
    idempotency_key: IdempotencyKey | None,
    source_metadata: SourceMetadata | None,
) -> CommandResult:
    return dispatch(
        command,
        actor=actor,
        library=actor.library,
        #: Caller's key else fresh; blank refused.
        idempotency_key=(
            str(uuid.uuid7()) if idempotency_key is None else idempotency_key
        ),
        correlation_id=correlation_id,
        source_metadata=source_metadata,
    )


def create_device(
    actor: User,
    *,
    name: str,
    device_type: str,
    correlation_id: uuid.UUID,
    access_end: WayActStatement | None = None,
    idempotency_key: IdempotencyKey | None = None,
    source_metadata: SourceMetadata | None = None,
) -> Device:
    """State a device; answer its row."""
    with answered(SUBJECT):
        result = _dispatch(
            CreateDevice(name=name, type=device_type, access_end=access_end),
            actor=actor,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            source_metadata=source_metadata,
        )
    return Device.objects.get(pk=created_aggregate_id(result), library=actor.library)


def restate_device(
    actor: User,
    device: Device,
    *,
    name: str | None = None,
    device_type: str | None = None,
    access_end: WayActStatement | None,
    correlation_id: uuid.UUID,
) -> None:
    """Move the end, then describe; one correlation.

    The end goes first: a racer can refuse it,
    and the description then stays unsent.
    """
    command = _access_end_command(device, access_end)
    if command is not None:
        with answered(SUBJECT):
            _dispatch(
                command,
                actor=actor,
                correlation_id=correlation_id,
                idempotency_key=None,
                source_metadata=None,
            )
    with answered(SUBJECT):
        _dispatch(
            DescribeDevice(device_id=device.pk, name=name, type=device_type),
            actor=actor,
            correlation_id=correlation_id,
            idempotency_key=None,
            source_metadata=None,
        )


def _access_end_command(
    device: Device, access_end: WayActStatement | None
) -> Command | None:
    match endpoint_move(stated(device, DEVICE_ACCESS_END), access_end):
        case Act(statement):
            return EndDeviceAccess(device_id=device.pk, statement=statement)
        case Correct(statement):
            return CorrectDeviceAccessEnd(device_id=device.pk, statement=statement)
        case Void():
            return VoidDeviceAccessEnd(device_id=device.pk)
        case Nothing():
            return None
        case unhandled:
            assert_never(unhandled)


def remove_device(
    actor: User,
    device: Device,
    *,
    correlation_id: uuid.UUID,
    idempotency_key: IdempotencyKey | None = None,
    source_metadata: SourceMetadata | None = None,
) -> CommandResult:
    """Take a device out of the library."""
    with answered(SUBJECT):
        return _dispatch(
            RemoveDevice(device_id=device.pk),
            actor=actor,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            source_metadata=source_metadata,
        )


def restore_device(
    actor: User,
    device: Device,
    *,
    correlation_id: uuid.UUID,
    idempotency_key: IdempotencyKey | None = None,
    source_metadata: SourceMetadata | None = None,
) -> CommandResult:
    """Put a removed device back."""
    with answered(SUBJECT):
        return _dispatch(
            RestoreDevice(device_id=device.pk),
            actor=actor,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            source_metadata=source_metadata,
        )
