from datetime import datetime, timedelta, timezone as dt_timezone

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from games.models import Device, Game, Platform, Session

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(username="tester", password="pw")


@pytest.fixture
def auth_client(user):
    client = Client()
    client.force_login(user)
    return client


def test_existing_endpoint_requires_auth():
    # Anonymous client hits an existing GET endpoint -> 401 after API-wide auth.
    response = Client().get("/api/platforms/groups")
    assert response.status_code == 401


def test_existing_endpoint_allows_logged_in(auth_client):
    response = auth_client.get("/api/platforms/groups")
    assert response.status_code == 200


def _make_session(**overrides):
    platform = Platform.objects.create(name="PC")
    game = Game.objects.create(name="Hades", platform=platform)
    device = Device.objects.create(name="Deck", type="h")
    fields = dict(
        game=game,
        device=device,
        timestamp_start=datetime(2026, 6, 24, 18, 0, tzinfo=dt_timezone.utc),
        timestamp_end=None,
        duration_manual=timedelta(0),
        note="",
        emulated=False,
    )
    fields.update(overrides)
    return Session.objects.create(**fields)


def test_session_detail_shape(auth_client):
    session = _make_session(
        timestamp_end=datetime(2026, 6, 24, 19, 0, tzinfo=dt_timezone.utc),
        duration_manual=timedelta(minutes=30),
    )
    response = auth_client.get(f"/api/session/{session.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == session.id
    assert data["game"] == {
        "id": session.game.id,
        "name": "Hades",
        "platform": {"name": "PC", "icon": session.game.platform.icon},
    }
    assert data["device"] == {"id": session.device.id, "name": "Deck", "type": "h"}
    assert data["timestamp_start"] == "2026-06-24T18:00:00Z"
    assert data["timestamp_end"] == "2026-06-24T19:00:00Z"
    assert data["duration_manual_seconds"] == 1800
    assert data["is_manual"] is True
    assert data["emulated"] is False
    assert "modified_at" in data and "created_at" in data


def test_session_detail_open_session_null_end(auth_client):
    session = _make_session()  # timestamp_end=None, manual=0
    data = auth_client.get(f"/api/session/{session.id}").json()
    assert data["timestamp_end"] is None
    assert data["duration_manual_seconds"] == 0
    assert data["is_manual"] is False


@pytest.mark.parametrize(
    "manual,expected",
    [
        (timedelta(0), False),
        (timedelta(minutes=5), True),
        (timedelta(minutes=-5), True),  # negative still counts as manual
    ],
)
def test_session_is_manual_matrix(auth_client, manual, expected):
    # NB: Session.save() coerces a None duration_manual to timedelta(0),
    # so the null case is unreachable via normal save and not tested here.
    # is_manual is shipped explicitly (not derived client-side) to stay correct
    # for negative/sub-second durations and to match server display exactly.
    session = _make_session(duration_manual=manual)
    data = auth_client.get(f"/api/session/{session.id}").json()
    assert data["is_manual"] is expected


def test_session_detail_404(auth_client):
    response = auth_client.get("/api/session/999999")
    assert response.status_code == 404


def test_session_detail_requires_auth():
    session = _make_session()
    assert Client().get(f"/api/session/{session.id}").status_code == 401
