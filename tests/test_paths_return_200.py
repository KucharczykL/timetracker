from datetime import datetime
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from games.models import Game, Platform, Purchase

ZONEINFO = ZoneInfo(settings.TIME_ZONE)


# DEBUG on turns every smoke test below into an id-uniqueness check: the page
# assembly in common/layout.py only runs assert_unique_element_ids under DEBUG,
# so with pytest-django's forced DEBUG=False a page that 500s the moment a
# developer opens it with `make dev` passes CI silently (issue #529). INTERNAL_IPS
# is cleared for the same reason tests/conftest.py's debug_page_rendering fixture
# clears it — debug_toolbar's show_toolbar() reads both live, and its URLs were
# never registered because timetracker.urls saw DEBUG=False at import time.
@override_settings(DEBUG=True, INTERNAL_IPS=[])
class PathWorksTest(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_superuser(
            username="testuser", email="test@example.com", password="testpass"
        )
        self.client.force_login(self.user)
        library = self.user.library
        self.platform = Platform.objects.create(
            library=library, name="Test Platform", icon="test"
        )
        self.game = Game.objects.create(
            library=library, name="Test Game", platform=self.platform
        )
        self.purchase = Purchase.objects.create(
            date_purchased=datetime(2022, 9, 26, 14, 58, tzinfo=ZONEINFO),
            platform=self.platform,
            library=library,
            price=43,
            price_currency="CZK",
            converted_price=14.5,
            converted_currency="CNY",
        )
        self.purchase.games.add(self.game)
        # A second purchase with identical prices: PurchasePrice's popover used
        # to hash its id from its own rendered content, so this row collided with
        # the one above and both the purchase list and the game detail page (which
        # lists a game's purchases) 500'd under DEBUG. Linked to the same game so
        # one fixture covers both.
        self.same_price_purchase = Purchase.objects.create(
            date_purchased=datetime(2022, 9, 27, 14, 58, tzinfo=ZONEINFO),
            platform=self.platform,
            library=library,
            price=43,
            price_currency="CZK",
            converted_price=14.5,
            converted_currency="CNY",
        )
        self.same_price_purchase.games.add(self.game)

    def test_index_redirects_to_tracker(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)

    def test_tracker_page_returns_200(self):
        response = self.client.get("/tracker/", follow=True)
        self.assertEqual(response.status_code, 200)

    def test_library_page_returns_200(self):
        response = self.client.get(reverse("games:library"))
        self.assertEqual(response.status_code, 200)

    def test_game_list_returns_200(self):
        response = self.client.get(reverse("games:list_games"), follow=True)
        self.assertEqual(response.status_code, 200)

    def test_view_game_returns_200(self):
        response = self.client.get(reverse("games:view_game", args=[self.game.id]))
        self.assertEqual(response.status_code, 200)

    def test_add_game_returns_200(self):
        response = self.client.get(reverse("games:add_game"))
        self.assertEqual(response.status_code, 200)

    def test_stats_returns_200(self):
        response = self.client.get(reverse("games:stats_alltime"))
        self.assertEqual(response.status_code, 200)

    def test_list_sessions_returns_200(self):
        response = self.client.get(reverse("games:list_sessions"))
        self.assertEqual(response.status_code, 200)

    def test_list_playevents_returns_200(self):
        response = self.client.get(reverse("games:list_playevents"))
        self.assertEqual(response.status_code, 200)

    def test_list_purchases_returns_200(self):
        response = self.client.get(reverse("games:list_purchases"))
        self.assertEqual(response.status_code, 200)

    def test_platform_groups_api_returns_200(self):
        # Distinct platform groups are returned as string-valued options.
        Platform.objects.create(name="Switch", icon="switch", group="Nintendo")
        response = self.client.get("/api/platforms/groups")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        groups = {item["value"] for item in body}
        self.assertIn("Nintendo", groups)

        filtered = self.client.get("/api/platforms/groups?q=nin")
        self.assertEqual(filtered.status_code, 200)
        self.assertEqual({item["value"] for item in filtered.json()}, {"Nintendo"})
