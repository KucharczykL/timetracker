"""Add, edit, remove and restore a device through its pages."""

import pytest
from devices import create_device, remove_device
from django.urls import reverse

from games.models import Device, LibraryEvent
from games.writes.answers import CONFLICT_STATUS, CommandFailed

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def logged_in(client, owned_user):
    client.force_login(owned_user)
    return client


def _device_events(device: Device) -> list[str]:
    return list(
        LibraryEvent.objects.filter(aggregate_id=device.pk)
        .order_by("sequence")
        .values_list("event_type", flat=True)
    )


def test_adding_states_a_creation(logged_in, owned_library):
    response = logged_in.post(
        reverse("games:add_device"),
        {"name": " Steam Deck ", "type": Device.HANDHELD, "submission": "0" * 32},
    )

    assert response.status_code == 302
    device = Device.objects.get()
    assert (device.library, device.name, device.type) == (
        owned_library,
        "Steam Deck",
        Device.HANDHELD,
    )
    assert _device_events(device) == ["library.device.created"]


def test_a_submit_posted_twice_creates_one_device(logged_in):
    posted = {"name": "Deck", "type": Device.PC, "submission": "1" * 32}

    logged_in.post(reverse("games:add_device"), posted)
    logged_in.post(reverse("games:add_device"), posted)

    assert Device.objects.count() == 1


def test_the_add_page_renders_a_fresh_submission(logged_in):
    first = logged_in.get(reverse("games:add_device")).content.decode()
    second = logged_in.get(reverse("games:add_device")).content.decode()

    marker = 'name="submission" value="'
    assert marker in first
    assert first.split(marker)[1][:36] != second.split(marker)[1][:36]


def test_editing_states_each_differing_fact(logged_in, owned_library):
    device = create_device(owned_library, "Deck", Device.UNKNOWN)

    edit = logged_in.get(reverse("games:edit_device", args=[device.pk]))
    assert 'value="Deck"' in edit.content.decode()
    assert 'name="submission"' not in edit.content.decode()

    response = logged_in.post(
        reverse("games:edit_device", args=[device.pk]),
        {"name": "Steam Deck", "type": Device.UNKNOWN},
    )

    assert response.status_code == 302
    device.refresh_from_db()
    assert device.name == "Steam Deck"
    assert _device_events(device) == [
        "library.device.created",
        "library.device.name_changed",
    ]


def test_a_refused_edit_is_a_sentence_on_the_form(
    logged_in, owned_library, monkeypatch
):
    device = create_device(owned_library, "Deck")

    def refuse(*args, **kwargs):
        raise CommandFailed("That device cannot be named so.", CONFLICT_STATUS)

    monkeypatch.setattr("games.views.device.describe_device", refuse)

    response = logged_in.post(
        reverse("games:edit_device", args=[device.pk]),
        {"name": "Steam Deck", "type": Device.PC},
    )

    assert response.status_code == CONFLICT_STATUS
    assert "That device cannot be named so." in response.content.decode()
    device.refresh_from_db()
    assert device.name == "Deck"


def test_removing_and_restoring_state_their_events(logged_in, owned_library):
    device = create_device(owned_library, "Deck")

    logged_in.post(reverse("games:remove_device", args=[device.pk]))
    device.refresh_from_db()
    assert device.removed_at is not None

    logged_in.post(reverse("games:restore_device", args=[device.pk]))
    device.refresh_from_db()
    assert device.removed_at is None
    assert _device_events(device) == [
        "library.device.created",
        "library.device.removed",
        "library.device.restored",
    ]


def test_a_removed_device_cannot_be_edited(logged_in, owned_library):
    device = remove_device(create_device(owned_library, "Deck"))

    response = logged_in.get(reverse("games:edit_device", args=[device.pk]))

    assert response.status_code == 404
