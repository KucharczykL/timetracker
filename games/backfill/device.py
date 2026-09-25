"""Convert existing devices into their events."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import NamedTuple, cast, get_args

from django.contrib.auth.models import User
from django.db import connection, transaction
from django.db.models import Model, QuerySet

from games.events.append import LockedStream
from games.events.device import (
    DEVICE_CREATED,
    DeviceTypeValue,
    device_created,
    device_removed,
)
from games.events.idempotency import IdempotencyKey, idempotent_append
from games.events.rebuild import RebuildMode, rebuild_projections
from games.events.vocabulary import NewEvent
from games.models import (
    Device,
    LibraryEvent,
    LibraryEventReference,
    LibraryEventStreamHead,
    LibraryIdempotencyRecord,
    UserLibrary,
)
from games.projections import projection_models

ISSUE = 1274


class DeviceConversionRefused(Exception):
    """An unconvertible row or a differing replay."""


@dataclass(frozen=True, slots=True)
class DeviceConversion:
    """What one pass did."""

    #: Libraries holding a row the pass stated.
    libraries: tuple[UserLibrary, ...]
    converted: int


def _key(act: str, device_id: uuid.UUID) -> IdempotencyKey:
    return f"backfill:{ISSUE}:device:{act}:{device_id}"


def _refuse_unknown_types(devices: QuerySet[Device]) -> None:
    """Name rows whose type no payload spells."""
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


class DeviceRow(NamedTuple):
    """Named columns only; later columns cannot break."""

    pk: uuid.UUID
    library_id: uuid.UUID
    owner_id: int
    name: str
    type: str
    created_at: datetime
    removed_at: datetime | None


def _state(
    device: DeviceRow,
    *,
    act: str,
    event: NewEvent,
    correlation_id: uuid.UUID,
    library: UserLibrary,
    actor: User,
) -> None:
    def build(stream: LockedStream) -> Sequence[NewEvent]:
        return [event]

    recorded_at = device.created_at if act == "created" else device.removed_at
    idempotent_append(
        library,
        idempotency_key=_key(act, device.pk),
        command_input={"device": str(device.pk), "act": act},
        build=build,
        actor=actor,
        correlation_id=correlation_id,
        source_metadata={"origin": "backfill", "issue": ISSUE},
        recorded_at=recorded_at,
    )


def convert_devices(library: UserLibrary | None = None) -> DeviceConversion:
    """State unconverted devices; report what moved."""
    devices = Device.objects.all()
    if library is not None:
        devices = devices.filter(library=library)
    created = LibraryEvent.objects.filter(event_type=DEVICE_CREATED.event_type).values(
        "aggregate_id"
    )
    unconverted = devices.exclude(pk__in=created)
    if not unconverted.exists():
        return DeviceConversion((), 0)
    _require_the_schema_this_pass_was_written_for()
    _refuse_unknown_types(unconverted)
    rows = [
        DeviceRow(*values)
        for values in unconverted.order_by("created_at", "pk").values_list(
            "pk",
            "library_id",
            "library__user_id",
            "name",
            "type",
            "created_at",
            "removed_at",
        )
    ]
    #: Key columns only; stable across versions.
    libraries = UserLibrary.objects.only("pk", "user_id").in_bulk(
        {row.library_id for row in rows}
    )
    owners = User.objects.only("pk").in_bulk({row.owner_id for row in rows})
    #: All devices or none; nests safely.
    with transaction.atomic():
        for row in rows:
            _convert(row, library=libraries[row.library_id], actor=owners[row.owner_id])
    touched = dict.fromkeys(row.library_id for row in rows)
    return DeviceConversion(tuple(libraries[key] for key in touched), len(rows))


def _convert(device: DeviceRow, *, library: UserLibrary, actor: User) -> None:
    """Creation, and removal where removed."""
    correlation_id = uuid.uuid7()
    _state(
        device,
        act="created",
        #: Types checked first; payload spells each.
        event=device_created(
            device.name, cast(DeviceTypeValue, device.type), device_id=device.pk
        ),
        correlation_id=correlation_id,
        library=library,
        actor=actor,
    )
    if device.removed_at is not None:
        _state(
            device,
            act="removed",
            event=device_removed(device.pk),
            correlation_id=correlation_id,
            library=library,
            actor=actor,
        )


def _require_the_schema_this_pass_was_written_for() -> None:
    """Refuse when code outruns the schema."""
    models: tuple[type[Model], ...] = (
        LibraryEvent,
        LibraryEventReference,
        LibraryEventStreamHead,
        LibraryIdempotencyRecord,
        *projection_models(),
    )
    missing: list[str] = []
    with connection.cursor() as cursor:
        for model in models:
            table = model._meta.db_table
            held = {
                column.name
                for column in connection.introspection.get_table_description(
                    cursor, table
                )
            }
            missing += [
                f"{table}.{field.column}"
                for field in model._meta.concrete_fields
                if field.column not in held
            ]
    if missing:
        raise DeviceConversionRefused(
            "The device conversion runs today's code, which declares columns "
            f"this database does not hold yet: {', '.join(missing)}. Deploy the "
            "release that carries this migration, migrate, and move on from "
            "there."
        )


def require_replay_parity(libraries: Sequence[UserLibrary]) -> None:
    """Refuse unless replay reproduces the tables."""
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
