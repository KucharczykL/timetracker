"""Device writes; refusals become answers."""

import uuid

from django.contrib.auth.models import User

from games.commands.device import (
    CreateDevice,
    DescribeDevice,
    RemoveDevice,
    RestoreDevice,
)
from games.events.append import SourceMetadata
from games.events.dispatch import Command, CommandResult, dispatch
from games.events.idempotency import IdempotencyKey
from games.models import Device
from games.reads.events import created_aggregate_id
from games.writes.answers import SubjectNoun, answered

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
    idempotency_key: IdempotencyKey | None = None,
    source_metadata: SourceMetadata | None = None,
) -> Device:
    """State a new device; answer its row."""
    with answered(SUBJECT):
        result = _dispatch(
            CreateDevice(name=name, type=device_type),
            actor=actor,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            source_metadata=source_metadata,
        )
    return Device.objects.get(pk=created_aggregate_id(result), library=actor.library)


def describe_device(
    actor: User,
    device: Device,
    *,
    name: str | None = None,
    device_type: str | None = None,
    correlation_id: uuid.UUID,
    idempotency_key: IdempotencyKey | None = None,
    source_metadata: SourceMetadata | None = None,
) -> CommandResult:
    """State name, type, or both."""
    with answered(SUBJECT):
        return _dispatch(
            DescribeDevice(device_id=device.pk, name=name, type=device_type),
            actor=actor,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            source_metadata=source_metadata,
        )


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
