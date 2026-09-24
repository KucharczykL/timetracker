"""State every device a deployment holds as the events that make it.

The migration that converts devices runs this, and so does
`load_sample_data`, whose committed fixture holds device rows and no
device events. Both go when a squash elides that migration and the
fixture has been regenerated with the events.

Commands are not used: a command refuses a blank name the table may
hold, and this states what the table holds. Every row keeps its key,
so every session, record, preference and recorded reference keeps
naming it.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast, get_args

from django.db import transaction
from django.db.models import QuerySet

from games.events.append import LockedStream
from games.events.device import (
    DeviceTypeValue,
    device_created,
    device_removed,
)
from games.events.idempotency import IdempotencyKey, idempotent_append
from games.events.rebuild import RebuildMode, rebuild_projections
from games.events.vocabulary import NewEvent
from games.models import Device, LibraryEvent, UserLibrary
from games.projections import projection_models

ISSUE = 1274
CREATED_EVENT = "library.device.created"


class DeviceConversionRefused(Exception):
    """A row the pass cannot state, or a replay that disagrees."""


@dataclass(frozen=True, slots=True)
class DeviceConversion:
    """What one pass did."""

    #: Libraries holding a row the pass stated.
    libraries: tuple[UserLibrary, ...]
    converted: int


def _key(act: str, device: Device) -> IdempotencyKey:
    return f"backfill:{ISSUE}:device:{act}:{device.pk}"


def _refuse_unknown_types(devices: QuerySet[Device]) -> None:
    """Every row the payload cannot spell, named before anything appends."""
    known = get_args(DeviceTypeValue.__value__)
    unknown = list(
        devices.exclude(type__in=known)
        .order_by("library_id", "pk")
        .values_list("pk", "library_id", "type")
    )
    if unknown:
        named = "; ".join(
            f"device {pk} of library {library_id} has type {stated!r}"
            for pk, library_id, stated in unknown
        )
        raise DeviceConversionRefused(
            f"{len(unknown)} device(s) hold a type no event can record: {named}. "
            f"Set each to one of {', '.join(known)} and migrate again."
        )


def _state(
    device: Device,
    *,
    act: str,
    event: NewEvent,
    correlation_id: uuid.UUID,
) -> None:
    def build(stream: LockedStream) -> Sequence[NewEvent]:
        return [event]

    recorded_at = device.created_at if act == "created" else device.removed_at
    idempotent_append(
        device.library,
        idempotency_key=_key(act, device),
        command_input={"device": str(device.pk), "act": act},
        build=build,
        actor=device.library.user,
        correlation_id=correlation_id,
        source_metadata={"origin": "backfill", "issue": ISSUE},
        recorded_at=recorded_at,
    )


def convert_devices(library: UserLibrary | None = None) -> DeviceConversion:
    """State each device holding no creation event; answer what moved.

    Every library, or the one named.
    """
    devices = Device.objects.all()
    if library is not None:
        devices = devices.filter(library=library)
    _refuse_unknown_types(devices)
    created = LibraryEvent.objects.filter(event_type=CREATED_EVENT).values(
        "aggregate_id"
    )
    unconverted = list(
        devices.exclude(pk__in=created)
        .select_related("library__user")
        .order_by("created_at", "pk")
    )
    libraries: dict[uuid.UUID, UserLibrary] = {}
    #: One transaction, nested where a caller holds one: the pass
    #: states every device or none.
    with transaction.atomic():
        for device in unconverted:
            _convert(device)
            libraries.setdefault(device.library_id, device.library)
    return DeviceConversion(tuple(libraries.values()), len(unconverted))


def _convert(device: Device) -> None:
    """The row's creation, and its removal where it is removed."""
    correlation_id = uuid.uuid7()
    _state(
        device,
        act="created",
        #: Checked first: every stored type is one the payload spells.
        event=device_created(
            device.name, cast(DeviceTypeValue, device.type), device_id=device.pk
        ),
        correlation_id=correlation_id,
    )
    if device.removed_at is not None:
        _state(
            device,
            act="removed",
            event=device_removed(device.pk),
            correlation_id=correlation_id,
        )


def require_replay_parity(libraries: Sequence[UserLibrary]) -> None:
    """Refuse unless each library's replay reproduces its tables.

    The live classes, named: a migration's historical models do not
    subclass `ProjectionModel`, so the registry over them is empty.
    """
    models = projection_models()
    for library in libraries:
        report = rebuild_projections(library, mode=RebuildMode.CHECK, models=models)
        drifted = [
            table
            for table in report.tables
            if table.only_live or table.only_rebuilt or table.differing
        ]
        if drifted:
            named = "; ".join(
                f"{table.table}: {table.only_live} only live, "
                f"{table.only_rebuilt} only rebuilt, {table.differing} differing "
                f"({', '.join(table.sample)})"
                for table in drifted
            )
            raise DeviceConversionRefused(
                f"Library {library.pk} does not replay to its own tables after "
                f"the device conversion: {named}."
            )
