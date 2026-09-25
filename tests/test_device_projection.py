"""Device rows rebuilt from events."""

import uuid
from datetime import date, timedelta

import pytest
from devices import create_device, remove_device
from django.db import connection, transaction
from django.utils import timezone

from games.commands.device import DescribeDevice
from games.commands.playergame import TrackGame
from games.commands.playersession import CreateSession, DurationOnlyTiming
from games.events.dispatch import append_command, dispatch
from games.events.rebuild import RebuildMode, rebuild_projections
from games.events.reconcile import UnresolvedReferences, reconcile_references
from games.models import Device, Game, Playthrough

pytestmark = [pytest.mark.untracked_games, pytest.mark.django_db(transaction=True)]


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
    """A drifted row is rebuilt."""
    device = create_device(owned_library, "Deck", Device.HANDHELD)
    before = Device.objects.filter(pk=device.pk).values().get()
    Device.objects.filter(pk=device.pk).update(name="Drifted")

    assert _devices_drift(owned_library) == [(0, 0, 1)]
    rebuild_projections(owned_library, mode=RebuildMode.REBUILD)
    assert Device.objects.filter(pk=device.pk).values().get() == before


def test_a_lost_row_is_rebuilt_rather_than_refused(owned_library):
    """PROJECTED: a lost row is rebuilt."""
    device = create_device(owned_library, "Deck", Device.HANDHELD)
    before = Device.objects.filter(pk=device.pk).values().get()
    with connection.cursor() as cursor:
        #: Bypass the ORM guard: a lost row.
        cursor.execute("DELETE FROM games_device WHERE id = %s", [device.pk])

    assert reconcile_references(owned_library).resolves
    rebuild_projections(owned_library, mode=RebuildMode.REBUILD)

    assert Device.objects.filter(pk=device.pk).values().get() == before


def test_a_stream_naming_a_device_it_never_created_is_refused(owned_library):
    """The stream check catches uncreated devices."""
    stray = Device.objects.create(
        id=uuid.uuid7(),
        library=owned_library,
        name="Written, never stated",
        type=Device.PC,
        created_at=timezone.now(),
    )
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    dispatch(
        TrackGame(game_id=game.pk),
        actor=owned_library.user,
        library=owned_library,
        idempotency_key="track",
    )
    dispatch(
        CreateSession(
            playthrough_id=Playthrough.objects.get(player_game__game=game).pk,
            timing=DurationOnlyTiming(
                day=date(2024, 3, 1), duration=timedelta(hours=1)
            ),
            device_id=stray.pk,
        ),
        actor=owned_library.user,
        library=owned_library,
        idempotency_key="session",
    )

    with pytest.raises(UnresolvedReferences, match=str(stray.pk)):
        rebuild_projections(owned_library, mode=RebuildMode.CHECK)
