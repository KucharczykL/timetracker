import pytest
from django.core.exceptions import ValidationError

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
    device = Device.objects.create(
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
    foreign = Device.objects.create(
        library=user2.library,
        name="Foreign deck",
        type=Device.HANDHELD,
    )

    with pytest.raises(ValidationError, match="same library"):
        settings_commands.change_library_default_device(library, foreign)

    assert UserLibraryPreferences.objects.get(library=library).default_device_id is None


def test_library_default_device_mutation_can_clear(user, db):
    library = user.library
    device = Device.objects.create(
        library=library,
        name="Deck",
        type=Device.HANDHELD,
    )
    settings_commands.change_library_default_device(library, device)

    assert settings_commands.change_library_default_device(library, None) is True
    assert UserLibraryPreferences.objects.get(library=library).default_device_id is None


def test_library_default_device_api_rejects_foreign_and_clears(client, user, user2):
    own = Device.objects.create(library=user.library, name="Own device")
    foreign = Device.objects.create(library=user2.library, name="Foreign device")
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
    assert selected.json()["source"] == "user"
    assert selected.json()["namespace"] == "library"
    assert rejected.status_code == 404
    assert cleared.status_code == 200
    assert (
        UserLibraryPreferences.objects.get(library=user.library).default_device_id
        is None
    )
