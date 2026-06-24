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


def test_end_session_post_redirects_and_ends(auth_client, running_session):
    url = reverse("games:list_sessions_end_session", args=[running_session.pk])
    response = auth_client.post(url)
    assert response.status_code == 302
    assert response.url == reverse("games:list_sessions")
    running_session.refresh_from_db()
    assert running_session.timestamp_end is not None


def test_end_session_get_not_allowed(auth_client, running_session):
    url = reverse("games:list_sessions_end_session", args=[running_session.pk])
    response = auth_client.get(url)
    assert response.status_code == 405
    running_session.refresh_from_db()
    assert running_session.timestamp_end is None


def test_reset_session_start_get_shows_confirm_page(auth_client, running_session):
    original_start = running_session.timestamp_start
    url = reverse("games:list_sessions_reset_session_start", args=[running_session.pk])
    response = auth_client.get(url)
    body = response.content.decode()
    assert response.status_code == 200
    # A full confirm page whose form posts back to the same URL.
    assert f'action="{url}"' in body
    assert 'method="post"' in body
    assert "Reset to now" in body
    running_session.refresh_from_db()
    assert running_session.timestamp_start == original_start


def test_reset_session_start_post_redirects_and_resets(auth_client, running_session):
    original_start = running_session.timestamp_start
    url = reverse("games:list_sessions_reset_session_start", args=[running_session.pk])
    response = auth_client.post(url)
    assert response.status_code == 302
    assert response.url == reverse("games:list_sessions")
    running_session.refresh_from_db()
    assert running_session.timestamp_start > original_start


def test_clone_htmx_returns_hx_refresh(auth_client, running_session):
    # Clone is converted in a later phase; still uses the htmx refresh for now.
    url = reverse(
        "games:list_sessions_start_session_from_session",
        args=[running_session.pk],
    )
    before = Session.objects.count()
    response = auth_client.get(url, HTTP_HX_REQUEST="true")
    assert response.status_code == 204
    assert response.headers.get("HX-Refresh") == "true"
    assert Session.objects.count() == before + 1
