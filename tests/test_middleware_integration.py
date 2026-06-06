import json
from datetime import datetime
from zoneinfo import ZoneInfo

from django.conf import settings
from django.test import TestCase, Client

from games.models import Device, Game, Platform, Purchase, Session
from django.contrib.auth.models import User


class MiddlewareIntegrationTest(TestCase):
    """Integration tests for HTMXMessagesMiddleware.

    These tests hit real endpoints that use messages.success() to verify
    the full chain: API endpoint → messages → middleware → HX-Trigger header.
    """

    @staticmethod
    def _create_user():
        return User.objects.create_user(
            username="testuser", password="testpass123"
        )

    def setUp(self):
        self.client = Client()
        self.user = self._create_user()
        self.client.force_login(self.user)
        self.platform = Platform(name="Test Platform")
        self.platform.save()
        self.game = Game(name="Test Game", platform=self.platform)
        self.game.save()

    def test_non_htmx_request_with_message_gets_hx_trigger(self):
        """
        Regression test: vanilla fetch() requests that set Django messages
        must receive HX-Trigger so fetchWithHtmxTriggers can read them.
        """
        response = self.client.patch(
            f"/api/games/{self.game.id}/status",
            data=json.dumps({"status": "played"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 204)
        self.assertIn("HX-Trigger", response)
        data = json.loads(response["HX-Trigger"])
        self.assertIn("show-toast", data)
        self.assertEqual(data["show-toast"]["type"], "success")

    def test_session_device_api_endpoint_sends_hx_trigger(self):
        """
        Verify the session device API endpoint also produces HX-Trigger.
        This is the exact endpoint used by sessiondevice_selector.html.
        """
        device = Device(name="Test Device")
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
            data=json.dumps({"device_id": device.id}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 204)
        self.assertIn("HX-Trigger", response)
        data = json.loads(response["HX-Trigger"])
        self.assertIn("show-toast", data)
        self.assertEqual(data["show-toast"]["message"], "Device updated")

    def test_refund_purchase_returns_updated_row_with_hx_trigger(
        self,
    ):
        """
        Verify the refund endpoint returns the updated row HTML so the page
        swaps it in place without navigating away (preserving URL/query params).
        """
        purchase = Purchase.objects.create(
            date_purchased=datetime(2023, 1, 1),
            platform=self.platform,
        )
        purchase.games.set([self.game])
        response = self.client.post(
            f"/tracker/purchase/{purchase.id}/refund",
            data={"set_abandoned": ""},
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("HX-Redirect", response)
        self.assertIn("HX-Trigger", response)
        data = json.loads(response["HX-Trigger"])
        self.assertIn("show-toast", data)
        self.assertEqual(data["show-toast"]["message"], "Purchase refunded")
        # Verify the row HTML contains the updated row id
        body = response.content.decode()
        self.assertIn(f'purchase-row-{purchase.id}', body)
        # Verify OoO modal close element
        self.assertIn('hx-swap-oob', body)
        self.assertIn('refund-confirmation-modal', body)
        # Verify the purchase is actually refunded
        purchase.refresh_from_db()
        self.assertIsNotNone(purchase.date_refunded)
