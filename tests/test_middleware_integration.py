import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from devices import create_device
from django.contrib.auth.models import User
from django.test import Client, TestCase
from session_rows import session_row

from games.models import Game, Platform


class MiddlewareIntegrationTest(TestCase):
    """Integration tests for ToastMessagesMiddleware.

    These tests hit real endpoints that use messages.success() to verify
    the full chain: API endpoint → messages → middleware → X-Events header.
    """

    @staticmethod
    def _create_user():
        return User.objects.create_user(username="testuser", password="testpass123")

    def setUp(self):
        self.client = Client()
        self.user = self._create_user()
        self.client.force_login(self.user)
        self.platform = Platform(library=self.user.library, name="Test Platform")
        self.platform.save()
        self.game = Game(
            library=self.user.library, name="Test Game", platform=self.platform
        )
        self.game.save()


@pytest.mark.django_db(transaction=True)
def test_a_fetch_with_a_message_gets_the_events_header(client, owned_user):
    """A plain fetch() gets X-Events.

    fetchWithEvents reads the header, so the toast depends on it.
    """
    #: Out of the TestCase, because the PATCH dispatches.
    #: A transactional class truncates for all to serve one.
    client.force_login(owned_user)
    game = Game.objects.create(library=owned_user.library, name="Test Game")

    response = client.patch(
        f"/api/games/{game.id}/status",
        data=json.dumps({"status": "played"}),
        content_type="application/json",
    )

    assert response.status_code == 204
    trigger = json.loads(response["X-Events"])
    assert trigger["show-toast"][-1]["type"] == "success"


#: Out of the TestCase: the device PATCH dispatches, and a dispatch
#: opens the transaction it retries.
@pytest.mark.django_db(transaction=True)
def test_session_device_api_endpoint_sends_the_events_header(client, owned_user):
    """The session device API endpoint produces X-Events too."""
    library = owned_user.library
    game = Game.objects.create(library=library, name="Test Game")
    device = create_device(library=library, name="Test Device")
    session = session_row(
        game, started_at=datetime(2022, 9, 26, 14, 58, tzinfo=ZoneInfo("UTC"))
    )
    client.force_login(owned_user)

    response = client.patch(
        f"/api/session/{session.id}/device",
        data=json.dumps({"device_id": str(device.id)}),
        content_type="application/json",
    )

    assert response.status_code == 204
    assert "X-Events" in response
    data = json.loads(response["X-Events"])
    assert data["show-toast"][-1]["message"] == "Device updated"
