"""One row per device, rebuilt from its events."""

import uuid

import pytest
from devices import create_device, remove_device
from django.db import transaction

from games.commands.device import DescribeDevice
from games.events.dispatch import append_command
from games.events.rebuild import RebuildMode, rebuild_projections
from games.models import Device

pytestmark = pytest.mark.django_db(transaction=True)


def _devices_drift(library) -> list[tuple[int, int, int]]:
    report = rebuild_projections(library, mode=RebuildMode.CHECK)
    return [
        (table.only_live, table.only_rebuilt, table.differing)
        for table in report.tables
        if table.table == "games_device"
    ]


def test_every_event_replays_to_the_same_rows(owned_library):
    kept = create_device(owned_library, "Deck", Device.UNKNOWN)
    with transaction.atomic():
        append_command(
            DescribeDevice(device_id=kept.pk, name="Steam Deck", type=Device.HANDHELD),
            actor=owned_library.user,
            library=owned_library,
            idempotency_key=str(uuid.uuid7()),
            correlation_id=uuid.uuid7(),
        )
    remove_device(create_device(owned_library, "Old laptop", Device.PC))
    before = list(Device.objects.order_by("pk").values())

    assert _devices_drift(owned_library) == [(0, 0, 0)]
    assert list(Device.objects.order_by("pk").values()) == before


def test_a_rebuild_puts_back_a_lost_row(owned_library):
    """The replay writes the row, so a lost one is recovered, not refused."""
    device = create_device(owned_library, "Deck", Device.HANDHELD)
    before = Device.objects.filter(pk=device.pk).values().get()
    Device.objects.filter(pk=device.pk).update(name="Drifted")

    assert _devices_drift(owned_library) == [(0, 0, 1)]
    rebuild_projections(owned_library, mode=RebuildMode.REBUILD)
    assert Device.objects.filter(pk=device.pk).values().get() == before
