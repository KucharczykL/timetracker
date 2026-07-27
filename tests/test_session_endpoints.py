import pytest
from django.urls import reverse
from django.utils import timezone

from games.models import Device, Game, Platform, Session


@pytest.fixture
def auth_client(client, django_user_model):
    user = django_user_model.objects.create_user(username="u", password="p")
    client.force_login(user)
    return client


@pytest.fixture
def running_session(db):
    platform = Platform.objects.create(name="PC")
    game = Game.objects.create(name="Hades", platform=platform)
    device = Device.objects.create(name="Deck")
    return Session.objects.create(
        game=game, device=device, timestamp_start=timezone.now()
    )


# Finish (end) and reset-start moved to PATCH /api/session/<id>; their behavior
# is covered by the API tests in tests/test_api.py (test_session_patch_*).


def test_clone_is_post_only(auth_client, running_session):
    url = reverse(
        "games:list_sessions_start_session_from_session",
        args=[running_session.pk],
    )
    assert auth_client.get(url).status_code == 405


def test_clone_post_creates_a_session_and_redirects(auth_client, running_session):
    url = reverse(
        "games:list_sessions_start_session_from_session",
        args=[running_session.pk],
    )
    before = Session.objects.count()
    response = auth_client.post(url)
    assert response.status_code == 302
    assert response["Location"] == reverse("games:list_sessions")
    assert Session.objects.count() == before + 1
