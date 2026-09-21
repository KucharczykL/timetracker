"""The rows a picker's create row makes.

A name is the only fact stated. Every other rule is the
form's, which is the form the add page runs.
"""

import pytest

from games.models import Device, Platform

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def user(owned_user):
    return owned_user


def _create(client, path: str, name: str):
    return client.post(path, {"name": name}, content_type="application/json")


def test_a_device_is_created_with_the_unknown_type(client, user):
    client.force_login(user)

    response = _create(client, "/api/devices/", "Steam Deck")

    assert response.status_code == 201
    device = Device.objects.get(library=user.library, name="Steam Deck")
    assert response.json() == {"value": str(device.pk), "label": "Steam Deck"}
    assert device.type == Device.UNKNOWN


def test_a_platform_is_created_private_to_the_library(client, user):
    client.force_login(user)

    response = _create(client, "/api/platforms/", "Arcade")

    assert response.status_code == 201
    platform = Platform.objects.get(name="Arcade")
    assert platform.library_id == user.library.pk
    assert response.json() == {"value": str(platform.pk), "label": "Arcade"}


def test_a_created_platform_takes_its_icon_from_its_name(client, user):
    client.force_login(user)

    _create(client, "/api/platforms/", "Neo Geo")

    assert Platform.objects.get(name="Neo Geo").icon == "neo-geo"


def test_a_platform_shadowing_a_shared_row_is_refused(client, user):
    Platform.objects.create(name="Arcade")
    client.force_login(user)

    response = _create(client, "/api/platforms/", "Arcade")

    assert response.status_code == 422
    assert response.json()["detail"]
    assert Platform.objects.filter(library=user.library).count() == 0


def test_a_platform_the_library_already_holds_is_refused(client, user):
    client.force_login(user)
    _create(client, "/api/platforms/", "Arcade")

    response = _create(client, "/api/platforms/", "Arcade")

    assert response.status_code == 422
    assert Platform.objects.filter(library=user.library, name="Arcade").count() == 1


def test_a_refusal_queues_its_sentence(client, user):
    Platform.objects.create(name="Arcade")
    client.force_login(user)

    response = _create(client, "/api/platforms/", "Arcade")

    assert "HX-Trigger" in response.headers


def test_a_blank_name_is_refused(client, user):
    client.force_login(user)

    response = _create(client, "/api/devices/", "   ")

    assert response.status_code == 422
    assert Device.objects.filter(library=user.library).count() == 0


def test_another_library_creates_its_own_platform_of_the_same_name(
    client, user, django_user_model
):
    other = django_user_model.objects.create_user(username="second-owner")
    client.force_login(user)
    _create(client, "/api/platforms/", "Arcade")
    client.force_login(other)

    response = _create(client, "/api/platforms/", "Arcade")

    assert response.status_code == 201
    assert Platform.objects.filter(name="Arcade").count() == 2


def test_a_device_the_library_holds_is_answered_once(client, user):
    """The window a create row judges on shows ten rows."""
    held = Device.objects.create(library=user.library, name="Steam Deck")
    client.force_login(user)

    response = _create(client, "/api/devices/", "steam deck")

    assert response.status_code == 201
    assert response.json() == {"value": str(held.pk), "label": "Steam Deck"}
    assert Device.objects.filter(library=user.library).count() == 1


def test_a_device_of_another_library_is_made_here(client, user, django_user_model):
    """A name is private, so another library's row blocks none."""
    other = django_user_model.objects.create_user(username="other", password="x")
    Device.objects.create(library=other.library, name="Steam Deck")
    client.force_login(user)

    response = _create(client, "/api/devices/", "Steam Deck")

    assert response.status_code == 201
    assert Device.objects.filter(library=user.library, name="Steam Deck").count() == 1
