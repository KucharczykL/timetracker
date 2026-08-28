import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from django.contrib.auth.models import User
from django.test import Client, TestCase

from games.models import Device, Game, Platform, Purchase, Session


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

    def test_session_device_api_endpoint_sends_hx_trigger(self):
        """
        Verify the session device API endpoint also produces HX-Trigger.
        This is the exact endpoint used by sessiondevice_selector.html.
        """
        device = Device(library=self.user.library, name="Test Device")
        device.save()
        zt = ZoneInfo(settings.TIME_ZONE)
        session = Session(
            game=self.game,
            device=device,
            timestamp_start=datetime(2022, 9, 26, 14, 58, tzinfo=zt),
        )
        session.save()

        response = self.client.patch(
            f"/api/session/{session.id}/device",
            data=json.dumps({"device_id": str(device.id)}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 204)
        self.assertIn("HX-Trigger", response)
        data = json.loads(response["HX-Trigger"])
        self.assertIn("show-toast", data)
        self.assertEqual(data["show-toast"]["message"], "Device updated")


@pytest.mark.django_db(transaction=True)
def test_non_htmx_request_with_message_gets_hx_trigger(client, owned_user):
    """A vanilla fetch() that sets a message still gets HX-Trigger.

    fetchWithHtmxTriggers reads the header, so the toast depends on it.
    """
    #: Moved out of MiddlewareIntegrationTest by #677: the PATCH now
    #: dispatches a command, and run_in_transaction refuses to open a
    #: transaction inside the one a TestCase wraps every test in. Making the
    #: whole class transactional would truncate between each of its tests to
    #: serve one.
    client.force_login(owned_user)
    game = Game.objects.create(library=owned_user.library, name="Test Game")

    response = client.patch(
        f"/api/games/{game.id}/status",
        data=json.dumps({"status": "p"}),
        content_type="application/json",
    )

    assert response.status_code == 204
    trigger = json.loads(response["HX-Trigger"])
    assert trigger["show-toast"]["type"] == "success"


@pytest.mark.django_db(transaction=True)
def test_refund_purchase_returns_updated_row_with_hx_trigger(client, owned_user):
    """The refund answers the updated row, so the page swaps it in place.

    A navigation would lose the URL and its query parameters.
    """
    #: Moved out of MiddlewareIntegrationTest by #677: the refund now
    #: dispatches a command for every game it covers, and run_in_transaction
    #: refuses to open a transaction inside the one a TestCase wraps every
    #: test in.
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
