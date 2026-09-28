"""Stating that a library's access to a device ended."""

import uuid
from datetime import UTC, datetime

import pytest
from devices import create_device, end_device_access, remove_device
from django.db import IntegrityError, transaction

from games.commands.device import (
    UNKNOWN_WAY,
    CorrectDeviceAccessEnd,
    CreateDevice,
    EndDeviceAccess,
    VoidDeviceAccessEnd,
)
from games.commands.endpoint import WayActStatement
from games.end_ways import EndWay
from games.endpoints import DEVICE_ACCESS_END
from games.events.dispatch import (
    CommandOutcome,
    CommandRejected,
    CommandResult,
    dispatch,
)
from games.events.rebuild import RebuildMode, rebuild_projections
from games.models import Device, LibraryEvent
from games.reads.endpoints import stated
from games.reads.events import created_aggregate_id
from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.django_db(transaction=True)

MAY = TemporalValue.parse("2021-05")
RECORDED = datetime(2026, 9, 28, tzinfo=UTC)
JUNE = TemporalValue.parse("2021-06")


def _dispatch(library, command) -> CommandResult:
    return dispatch(
        command,
        actor=library.user,
        library=library,
        idempotency_key=str(uuid.uuid7()),
    )


def _refused(library, command) -> CommandRejected:
    with pytest.raises(CommandRejected) as refused:
        _dispatch(library, command)
    return refused.value


def _event_types(device: Device) -> list[str]:
    return list(
        LibraryEvent.objects.filter(aggregate_id=device.pk)
        .order_by("sequence")
        .values_list("event_type", flat=True)
    )


def _end(device, way=EndWay.SOLD, when=MAY, note=""):
    return EndDeviceAccess(
        device_id=device.pk, statement=WayActStatement(when, way, note)
    )


def _correct(device, way=EndWay.SOLD, when=MAY, note=""):
    return CorrectDeviceAccessEnd(
        device_id=device.pk, statement=WayActStatement(when, way, note)
    )


def test_ending_access_states_the_way_the_day_and_the_note(owned_library):
    device = create_device(owned_library)

    _dispatch(owned_library, _end(device, note="  to a friend  "))

    device.refresh_from_db()
    assert (
        device.access_end_way,
        device.access_ended,
        device.access_end_note,
    ) == ("sold", MAY, "to a friend")
    assert device.access_end_recorded_at is not None
    assert str(device.access_ended_lower) == "2021-05-01"
    assert _event_types(device)[-1] == "library.device.access_ended"


def test_the_same_end_again_is_unchanged(owned_library):
    device = end_device_access(create_device(owned_library), when=MAY)

    result = _dispatch(owned_library, _end(device))

    assert result.outcome is CommandOutcome.UNCHANGED


def test_a_second_end_is_refused(owned_library):
    device = end_device_access(create_device(owned_library), when=MAY)

    refused = _refused(owned_library, _end(device, way=EndWay.LOST))

    assert refused.sentence.startswith("This device already has an end recorded.")


def test_a_correction_of_the_way_alone_keeps_the_marker(owned_library):
    device = end_device_access(create_device(owned_library), when=MAY)
    marker = device.access_end_recorded_at

    _dispatch(owned_library, _correct(device, way=EndWay.LOST))

    device.refresh_from_db()
    assert (device.access_end_way, device.access_ended) == ("lost", MAY)
    assert device.access_end_recorded_at == marker
    assert _event_types(device)[-1] == "library.device.access_end_corrected"


def test_a_correction_of_a_held_device_is_refused(owned_library):
    device = create_device(owned_library)

    refused = _refused(owned_library, _correct(device))

    assert refused.sentence.startswith("This device has no end to correct.")


def test_a_void_puts_the_device_back_in_hand(owned_library):
    device = end_device_access(create_device(owned_library), when=MAY, note="x")

    _dispatch(owned_library, VoidDeviceAccessEnd(device_id=device.pk))

    device.refresh_from_db()
    assert stated(device, DEVICE_ACCESS_END) is None
    assert (device.access_end_way, device.access_end_note) == ("", "")
    assert device.access_ended is None


def test_a_void_of_a_held_device_is_unchanged(owned_library):
    device = create_device(owned_library)

    result = _dispatch(owned_library, VoidDeviceAccessEnd(device_id=device.pk))

    assert result.outcome is CommandOutcome.UNCHANGED


def test_a_removed_device_refuses_an_end_and_a_correction(owned_library):
    held = remove_device(create_device(owned_library, "Held"))
    ended = remove_device(end_device_access(create_device(owned_library, "Ended")))

    for command in (_end(held), _correct(ended)):
        refused = _refused(owned_library, command)
        assert refused.sentence.startswith("That device was removed.")


def test_a_removed_device_answers_a_repeat_void_before_refusing(owned_library):
    held = remove_device(create_device(owned_library, "Held"))
    ended = remove_device(end_device_access(create_device(owned_library, "Ended")))

    unchanged = _dispatch(owned_library, VoidDeviceAccessEnd(device_id=held.pk))
    refused = _refused(owned_library, VoidDeviceAccessEnd(device_id=ended.pk))

    assert unchanged.outcome is CommandOutcome.UNCHANGED
    assert refused.sentence.startswith("That device was removed.")


def test_a_way_no_device_takes_is_refused_with_a_sentence(owned_library):
    device = create_device(owned_library)
    statement = WayActStatement(None, "refunded", "")  # type: ignore[arg-type]

    refused = _refused(
        owned_library, EndDeviceAccess(device_id=device.pk, statement=statement)
    )

    assert refused.sentence == UNKNOWN_WAY


def test_a_device_created_after_it_left_states_both_in_one_build(owned_library):
    result = _dispatch(
        owned_library,
        CreateDevice(
            name="Old console",
            type=Device.CONSOLE,
            access_end=WayActStatement(None, EndWay.GIVEN_AWAY, ""),
        ),
    )

    device = Device.objects.get(pk=created_aggregate_id(result))
    assert _event_types(device) == [
        "library.device.created",
        "library.device.access_ended",
    ]
    assert device.access_end_way == "given_away"


def test_a_creation_with_a_foreign_way_appends_nothing(owned_library):
    statement = WayActStatement(None, "refunded", "")  # type: ignore[arg-type]

    refused = _refused(
        owned_library,
        CreateDevice(name="Old console", type=Device.CONSOLE, access_end=statement),
    )

    assert refused.sentence == UNKNOWN_WAY
    assert not LibraryEvent.objects.filter(
        event_type__startswith="library.device."
    ).exists()


def test_every_access_end_event_replays_to_the_same_rows(owned_library):
    device = end_device_access(create_device(owned_library, "Deck"), when=MAY)
    _dispatch(owned_library, _correct(device, way=EndWay.STOLEN, when=JUNE))
    voided = end_device_access(create_device(owned_library, "Phone"))
    _dispatch(owned_library, VoidDeviceAccessEnd(device_id=voided.pk))
    remove_device(end_device_access(create_device(owned_library, "Laptop")))
    before = list(Device.objects.order_by("pk").values())

    report = rebuild_projections(owned_library, mode=RebuildMode.CHECK)

    drift = [
        (table.only_live, table.only_rebuilt, table.differing)
        for table in report.tables
        if table.table == "games_device"
    ]
    assert drift == [(0, 0, 0)]
    assert list(Device.objects.order_by("pk").values()) == before


@pytest.mark.parametrize(
    "columns",
    [
        #: A way without the marker.
        {"access_end_way": "sold"},
        #: A marker beside a foreign way.
        {"access_end_way": "refunded", "access_end_recorded_at": RECORDED},
    ],
)
def test_the_database_backs_the_command(owned_library, columns):
    device = create_device(owned_library)

    with pytest.raises(IntegrityError), transaction.atomic():
        Device.objects.filter(pk=device.pk).update(**columns)
