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


def test_end_session_htmx_returns_row_and_oob_navbar(auth_client, running_session):
    url = reverse("games:list_sessions_end_session", args=[running_session.pk])
    response = auth_client.get(url, HTTP_HX_REQUEST="true")
    body = response.content.decode()
    assert response.status_code == 200
    assert f'id="session-row-{running_session.pk}"' in body
    assert 'id="navbar-playtime"' in body
    assert 'hx-swap-oob="true"' in body
    running_session.refresh_from_db()
    assert running_session.timestamp_end is not None


def test_reset_session_start_htmx_returns_row_no_refresh_header(
    auth_client, running_session
):
    original_start = running_session.timestamp_start
    url = reverse("games:list_sessions_reset_session_start", args=[running_session.pk])
    response = auth_client.get(url, HTTP_HX_REQUEST="true")
    body = response.content.decode()
    assert response.status_code == 200
    assert f'id="session-row-{running_session.pk}"' in body
    assert 'id="navbar-playtime"' in body
    assert "HX-Refresh" not in response.headers
    running_session.refresh_from_db()
    assert running_session.timestamp_start > original_start


def test_clone_htmx_returns_hx_refresh(auth_client, running_session):
    url = reverse(
        "games:list_sessions_start_session_from_session",
        args=[running_session.pk],
    )
    before = Session.objects.count()
    response = auth_client.get(url, HTTP_HX_REQUEST="true")
    assert response.status_code == 204
    assert response.headers.get("HX-Refresh") == "true"
    assert Session.objects.count() == before + 1


def test_end_session_non_htmx_redirects(auth_client, running_session):
    url = reverse("games:list_sessions_end_session", args=[running_session.pk])
    response = auth_client.get(url)
    assert response.status_code == 302
    assert response.url == reverse("games:list_sessions")
