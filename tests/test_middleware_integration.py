import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth.models import User
from django.test import Client, TestCase
from session_rows import session_row

from games.models import Device, Game, Platform, Purchase


class MiddlewareIntegrationTest(TestCase):
    """Integration tests for HTMXMessagesMiddleware.

    These tests hit real endpoints that use messages.success() to verify
    the full chain: API endpoint → messages → middleware → HX-Trigger header.
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
def test_non_htmx_request_with_message_gets_hx_trigger(client, owned_user):
    """A plain fetch() still gets HX-Trigger.

    fetchWithHtmxTriggers reads the header, so the toast depends on it.
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
    trigger = json.loads(response["HX-Trigger"])
    assert trigger["show-toast"]["type"] == "success"


@pytest.mark.django_db(transaction=True)
def test_refund_purchase_returns_updated_row_with_hx_trigger(client, owned_user):
    """The refund answers a row, never a page.

    A navigation would lose the URL and its query parameters.
    """
    #: Out of the TestCase, because the refund dispatches.
    client.force_login(owned_user)
    platform = Platform.objects.create(library=owned_user.library, name="Test Platform")
    game = Game.objects.create(
        library=owned_user.library, name="Test Game", platform=platform
    )
    purchase = Purchase.objects.create(
        price_currency="CZK",
        library=owned_user.library,
        date_purchased=datetime(2023, 1, 1),
        platform=platform,
    )
    purchase.games.set([game])

    response = client.post(
        f"/tracker/purchase/{purchase.id}/refund",
        data={"set_abandoned": ""},
    )

    assert response.status_code == 200
    assert "HX-Redirect" not in response
    trigger = json.loads(response["HX-Trigger"])
    assert trigger["show-toast"]["message"] == "Purchase refunded"
    body = response.content.decode()
    assert f"purchase-row-{purchase.id}" in body
    #: The out-of-band template that closes the modal.
    assert "hx-swap-oob" in body
    assert "refund-confirmation-modal" in body
    purchase.refresh_from_db()
    assert purchase.date_refunded is not None


#: Out of the TestCase: the device PATCH dispatches, and a dispatch
#: opens the transaction it retries.
@pytest.mark.django_db(transaction=True)
def test_session_device_api_endpoint_sends_hx_trigger(client, owned_user):
    """The session device API endpoint produces HX-Trigger too."""
    library = owned_user.library
    game = Game.objects.create(library=library, name="Test Game")
    device = Device.objects.create(library=library, name="Test Device")
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
    assert "HX-Trigger" in response
    data = json.loads(response["HX-Trigger"])
    assert data["show-toast"]["message"] == "Device updated"
