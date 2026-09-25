import pytest
from devices import create_device
from django.core.exceptions import ValidationError
from django.db import connection

from games.events.rebuild import RebuildMode, rebuild_projections
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
