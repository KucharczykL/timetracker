import uuid

import pytest
from devices import create_device, end_device_access
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.urls import reverse

from games.commands.device import VoidDeviceAccessEnd
from games.end_ways import EndWay
from games.events.dispatch import append_command
from games.events.rebuild import RebuildMode, rebuild_projections
from games.forms import DEVICE_SEARCH_URL, HELD_DEVICES
from games.models import Device, UserLibraryPreferences
from timetracker import settings_commands


@pytest.fixture
def user(db, django_user_model):
    return django_user_model.objects.create_user(username="library-owner")


@pytest.fixture
def user2(db, django_user_model):
    return django_user_model.objects.create_user(username="other-library-owner")


def test_library_default_device_mutation_persists_and_reports_noop(user, db):
    library = user.library
    device = create_device(
        library=library,
        name="Deck",
        type=Device.HANDHELD,
    )

    assert settings_commands.change_library_default_device(library, device) is True
    first_updated_at = UserLibraryPreferences.objects.get(library=library).updated_at

    assert settings_commands.change_library_default_device(library, device) is False
    preferences = UserLibraryPreferences.objects.get(library=library)
    assert preferences.default_device == device
    assert preferences.updated_at == first_updated_at


def test_library_default_device_mutation_rejects_foreign_device(user, user2, db):
    library = user.library
    foreign = create_device(
        library=user2.library,
        name="Foreign deck",
        type=Device.HANDHELD,
    )

    with pytest.raises(ValidationError, match="same library"):
        settings_commands.change_library_default_device(library, foreign)

    assert UserLibraryPreferences.objects.get(library=library).default_device_id is None


def test_library_default_device_mutation_can_clear(user, db):
    library = user.library
    device = create_device(
        library=library,
        name="Deck",
        type=Device.HANDHELD,
    )
    settings_commands.change_library_default_device(library, device)

    assert settings_commands.change_library_default_device(library, None) is True
    assert UserLibraryPreferences.objects.get(library=library).default_device_id is None


def test_library_default_device_api_rejects_foreign_and_clears(client, user, user2):
    own = create_device(library=user.library, name="Own device")
    foreign = create_device(library=user2.library, name="Foreign device")
    client.force_login(user)

    selected = client.patch(
        "/api/library/default-device",
        data={"value": own.pk},
        content_type="application/json",
    )
    rejected = client.patch(
        "/api/library/default-device",
        data={"value": foreign.pk},
        content_type="application/json",
    )
    cleared = client.patch(
        "/api/library/default-device",
        data={"value": None},
        content_type="application/json",
    )

    assert selected.status_code == 200
    assert selected.json()["source"] == "library"
    assert selected.json()["namespace"] == "library"
    assert rejected.status_code == 404
    assert cleared.status_code == 200
    assert (
        UserLibraryPreferences.objects.get(library=user.library).default_device_id
        is None
    )


@pytest.mark.django_db(transaction=True)
def test_a_default_device_key_survives_a_rebuild(owned_library):
    """No foreign key blocks the swap."""
    device = create_device(owned_library, "Deck")
    owned_library.preferences.set_default_device(device)

    rebuild_projections(owned_library, mode=RebuildMode.REBUILD)

    preferences = UserLibraryPreferences.objects.get(library=owned_library)
    assert preferences.default_device == device


@pytest.mark.django_db(transaction=True)
def test_a_default_device_row_lost_reads_as_none(owned_library):
    """A lost device reads as no default."""
    device = create_device(owned_library, "Deck")
    owned_library.preferences.set_default_device(device)
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM games_device WHERE id = %s", [device.pk])

    preferences = UserLibraryPreferences.objects.get(library=owned_library)
    assert preferences.default_device_id == device.pk
    assert preferences.default_device is None


def _void(device: Device) -> None:
    with transaction.atomic():
        append_command(
            VoidDeviceAccessEnd(device_id=device.pk),
            actor=device.library.user,
            library=device.library,
            idempotency_key=str(uuid.uuid7()),
            correlation_id=uuid.uuid7(),
        )


def test_an_ended_default_is_no_default_until_the_end_is_voided(user):
    library = user.library
    device = create_device(library=library, name="Deck")
    settings_commands.change_library_default_device(library, device)

    end_device_access(device)
    preferences = UserLibraryPreferences.objects.get(library=library)
    assert preferences.default_device is None
    assert preferences.default_device_id == device.pk
    assert preferences.stored_default_device == device

    _void(device)
    preferences.refresh_from_db()
    assert preferences.default_device == device


def test_the_settings_page_holds_an_ended_default_by_name(client, user):
    library = user.library
    kept = create_device(library=library, name="Deck")
    settings_commands.change_library_default_device(library, kept)
    end_device_access(kept, way=EndWay.LOST)
    client.force_login(user)

    body = client.get(reverse("games:library")).content.decode()
    picker = body[body.index('name="default_device" search-url') :]
    picker = picker[: picker.index("</search-select>")]

    assert f'name="default_device" value="{kept.pk}"' in picker
    assert 'value="Deck"' in picker
    assert "Lost" not in picker
    assert "Lost, so new sessions name no device. Choose another." in body


def test_device_search_held_omits_an_ended_device(client, user):
    library = user.library
    create_device(library=library, name="Deck")
    end_device_access(create_device(library=library, name="Old laptop"))
    client.force_login(user)

    held = {key: source["value"] for key, source in HELD_DEVICES.items()}

    def labels(**params):
        answer = client.get(DEVICE_SEARCH_URL, params).json()
        return {row["label"] for row in answer}

    assert labels(**held) == {"Deck"}
    assert labels(**held, q="o") == set()
    assert labels() == {"Deck", "Old laptop"}


def test_the_api_refuses_an_ended_device_even_as_the_stored_default(client, user):
    library = user.library
    device = create_device(library=library, name="Deck")
    settings_commands.change_library_default_device(library, device)
    end_device_access(device)
    client.force_login(user)

    kept = client.patch(
        "/api/library/default-device",
        data={"value": device.pk},
        content_type="application/json",
    )
    cleared = client.patch(
        "/api/library/default-device",
        data={"value": None},
        content_type="application/json",
    )

    assert kept.status_code == 422
    assert cleared.status_code == 200
    assert UserLibraryPreferences.objects.get(library=library).default_device_id is None


def test_the_api_refuses_an_ended_device_as_a_new_default(client, user):
    ended = end_device_access(create_device(library=user.library, name="Old laptop"))
    client.force_login(user)

    refused = client.patch(
        "/api/library/default-device",
        data={"value": ended.pk},
        content_type="application/json",
    )

    assert refused.status_code == 422
    assert "Choose one you still have" in refused.json()["detail"]
    assert (
        UserLibraryPreferences.objects.get(library=user.library).default_device_id
        is None
    )
