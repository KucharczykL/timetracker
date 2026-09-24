"""Stating a device the library owns."""

import uuid

import pytest
from devices import create_device, remove_device

from games.commands.device import (
    NAME_REQUIRED,
    NAME_TOO_LONG,
    UNKNOWN_TYPE,
    CreateDevice,
    DescribeDevice,
    RemoveDevice,
    RestoreDevice,
)
from games.events.device import DeviceTypeValue
from games.events.dispatch import (
    CommandOutcome,
    CommandRejected,
    CommandResult,
    RowNotHeld,
    dispatch,
)
from games.models import Device, LibraryEvent

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def second_library(django_user_model):
    return django_user_model.objects.create_user(username="second-owner").library


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


def test_the_payload_spells_every_stored_type():
    """The recorded vocabulary and the column's choices are one list."""
    from typing import get_args

    assert set(get_args(DeviceTypeValue.__value__)) == {
        value for value, _label in Device.DEVICE_TYPES
    }


def test_it_creates_the_device(owned_library):
    device = create_device(owned_library, "  Steam Deck  ", Device.HANDHELD)

    assert (device.name, device.type, device.removed_at) == (
        "Steam Deck",
        Device.HANDHELD,
        None,
    )
    assert device.library == owned_library
    created = LibraryEvent.objects.get(aggregate_id=device.pk)
    assert created.event_type == "library.device.created"
    assert created.payload == {"name": "Steam Deck", "type": "Handheld"}
    assert device.created_at == created.recorded_at


@pytest.mark.parametrize(
    ("name", "device_type", "sentence"),
    (
        ("   ", Device.PC, NAME_REQUIRED),
        ("x" * 256, Device.PC, NAME_TOO_LONG),
        ("Deck", "Toaster", UNKNOWN_TYPE),
    ),
)
def test_a_creation_is_refused(owned_library, name, device_type, sentence):
    refused = _refused(owned_library, CreateDevice(name=name, type=device_type))

    assert refused.sentence == sentence
    assert not Device.objects.exists()


def test_a_held_name_is_not_refused(owned_library):
    """The column states no rule; the picker answers a held name itself."""
    create_device(owned_library, "Deck")
    create_device(owned_library, "Deck")

    assert Device.objects.filter(name="Deck").count() == 2


def test_a_description_states_one_event_per_differing_fact(owned_library):
    device = create_device(owned_library, "Deck", Device.UNKNOWN)

    _dispatch(
        owned_library,
        DescribeDevice(device_id=device.pk, name="Steam Deck", type=Device.HANDHELD),
    )

    device.refresh_from_db()
    assert (device.name, device.type) == ("Steam Deck", Device.HANDHELD)
    assert _event_types(device) == [
        "library.device.created",
        "library.device.name_changed",
        "library.device.type_changed",
    ]


def test_a_description_states_only_what_it_names(owned_library):
    device = create_device(owned_library, "Deck", Device.UNKNOWN)

    _dispatch(owned_library, DescribeDevice(device_id=device.pk, type=Device.PC))

    device.refresh_from_db()
    assert (device.name, device.type) == ("Deck", Device.PC)
    assert _event_types(device)[-1] == "library.device.type_changed"


def test_a_description_that_changes_nothing_is_unchanged(owned_library):
    device = create_device(owned_library, "Deck", Device.PC)

    result = _dispatch(
        owned_library,
        DescribeDevice(device_id=device.pk, name=" Deck ", type=Device.PC),
    )

    assert result.outcome is CommandOutcome.UNCHANGED
    assert _event_types(device) == ["library.device.created"]


def test_a_description_refuses_a_blank_name(owned_library):
    device = create_device(owned_library, "Deck")

    refused = _refused(owned_library, DescribeDevice(device_id=device.pk, name=""))

    assert refused.sentence == NAME_REQUIRED


def test_a_removed_device_refuses_a_description(owned_library):
    device = remove_device(create_device(owned_library, "Deck"))

    refused = _refused(owned_library, DescribeDevice(device_id=device.pk, name="New"))

    assert "Restore it" in refused.sentence


def test_another_librarys_device_is_not_held(owned_library, second_library):
    elsewhere = create_device(second_library, "Elsewhere")

    for command in (
        DescribeDevice(device_id=elsewhere.pk, name="Mine"),
        RemoveDevice(device_id=elsewhere.pk),
        RestoreDevice(device_id=elsewhere.pk),
    ):
        with pytest.raises(RowNotHeld):
            _dispatch(owned_library, command)


def test_removal_and_restoration_move_the_mark(owned_library):
    device = create_device(owned_library, "Deck")

    _dispatch(owned_library, RemoveDevice(device_id=device.pk))
    device.refresh_from_db()
    removed = LibraryEvent.objects.get(
        aggregate_id=device.pk, event_type="library.device.removed"
    )
    assert device.removed_at == removed.recorded_at

    _dispatch(owned_library, RestoreDevice(device_id=device.pk))
    device.refresh_from_db()
    assert device.removed_at is None


def test_a_repeated_mark_is_unchanged(owned_library):
    device = create_device(owned_library, "Deck")

    assert (
        _dispatch(owned_library, RestoreDevice(device_id=device.pk)).outcome
        is CommandOutcome.UNCHANGED
    )
    _dispatch(owned_library, RemoveDevice(device_id=device.pk))
    assert (
        _dispatch(owned_library, RemoveDevice(device_id=device.pk)).outcome
        is CommandOutcome.UNCHANGED
    )
