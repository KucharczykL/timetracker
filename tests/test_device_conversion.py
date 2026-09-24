"""Every device a deployment holds, stated as the events that make it."""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from django.db import connection

from games.backfill.device import (
    DeviceConversion,
    DeviceConversionRefused,
    convert_devices,
    require_replay_parity,
)
from games.commands.playergame import TrackGame
from games.commands.playersession import CreateSession, DurationOnlyTiming
from games.events.dispatch import dispatch
from games.events.reconcile import reconcile_references
from games.models import Device, Game, LibraryEvent, PlayerSession, Playthrough

pytestmark = [pytest.mark.untracked_games, pytest.mark.django_db(transaction=True)]

CREATED = datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)
REMOVED = datetime(2025, 6, 7, 8, 9, 10, tzinfo=UTC)


def _row(library, name, *, device_type=Device.PC, removed_at=None) -> Device:
    """A row as a deployment holds it: written, with no event."""
    return Device.objects.create(
        id=uuid.uuid7(),
        library=library,
        name=name,
        type=device_type,
        created_at=CREATED,
        removed_at=removed_at,
    )


def _events(device: Device) -> list[LibraryEvent]:
    return list(
        LibraryEvent.objects.filter(aggregate_id=device.pk).order_by("sequence")
    )


def test_a_device_is_stated_under_its_own_key(owned_library):
    device = _row(owned_library, "Deck", device_type=Device.HANDHELD)

    conversion = convert_devices()

    assert conversion.converted == 1
    assert [library.pk for library in conversion.libraries] == [owned_library.pk]
    [created] = _events(device)
    assert created.event_type == "library.device.created"
    assert created.payload == {"name": "Deck", "type": "Handheld"}
    assert created.recorded_at == CREATED
    assert created.actor == owned_library.user
    assert created.source_metadata == {"origin": "backfill", "issue": 1274}
    require_replay_parity(conversion.libraries)


def test_a_removed_device_converts_removed(owned_library):
    device = _row(owned_library, "Old laptop", removed_at=REMOVED)

    convert_devices()

    assert [event.event_type for event in _events(device)] == [
        "library.device.created",
        "library.device.removed",
    ]
    assert _events(device)[1].recorded_at == REMOVED
    device.refresh_from_db()
    assert device.removed_at == REMOVED
    require_replay_parity([owned_library])


def test_a_blank_name_converts_as_stored(owned_library):
    """The command would refuse it; the conversion states what the table holds."""
    device = _row(owned_library, "")

    convert_devices()

    assert _events(device)[0].payload["name"] == ""
    require_replay_parity([owned_library])


def test_a_type_no_event_can_record_refuses_by_row(owned_library):
    device = _row(owned_library, "Deck", device_type="Toaster")

    with pytest.raises(DeviceConversionRefused, match=str(device.pk)):
        convert_devices()

    assert not LibraryEvent.objects.filter(
        event_type__startswith="library.device"
    ).exists()


def test_a_second_pass_appends_nothing(owned_library):
    _row(owned_library, "Deck")
    convert_devices()
    appended = LibraryEvent.objects.count()

    assert convert_devices().converted == 0
    assert LibraryEvent.objects.count() == appended


def test_one_library_is_converted_alone(owned_library, django_user_model):
    other = django_user_model.objects.create_user(username="other").library
    mine = _row(owned_library, "Mine")
    theirs = _row(other, "Theirs")

    convert_devices(owned_library)

    assert _events(mine)
    assert not _events(theirs)


def test_a_session_naming_a_converted_device_keeps_naming_it(owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    dispatch(
        TrackGame(game_id=game.pk),
        actor=owned_library.user,
        library=owned_library,
        idempotency_key="track",
    )
    run = Playthrough.objects.get(player_game__game=game)
    device = _row(owned_library, "Deck")
    dispatch(
        CreateSession(
            playthrough_id=run.pk,
            timing=DurationOnlyTiming(
                day=date(2024, 3, 1), duration=timedelta(hours=1)
            ),
            device_id=device.pk,
        ),
        actor=owned_library.user,
        library=owned_library,
        idempotency_key="session",
    )

    #: Before the conversion, the stream names a device it never created.
    assert not reconcile_references(owned_library).resolves

    convert_devices()

    assert reconcile_references(owned_library).resolves
    assert PlayerSession.objects.get().device_id == device.pk
    require_replay_parity([owned_library])


def test_a_database_holding_no_device_reads_nothing_more(owned_library):
    """So a fresh one migrates under any later schema."""
    assert convert_devices() == DeviceConversion((), 0)


def test_a_schema_behind_the_code_is_refused_by_name(owned_library, monkeypatch):
    _row(owned_library, "Deck")
    described = connection.introspection.get_table_description

    def without_a_column(cursor, table):
        columns = described(cursor, table)
        if table == "games_device":
            return [column for column in columns if column.name != "removed_at"]
        return columns

    monkeypatch.setattr(
        connection.introspection, "get_table_description", without_a_column
    )

    with pytest.raises(DeviceConversionRefused, match="games_device.removed_at"):
        convert_devices()
    assert not LibraryEvent.objects.filter(
        event_type__startswith="library.device"
    ).exists()
