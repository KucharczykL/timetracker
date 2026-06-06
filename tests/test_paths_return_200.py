from datetime import datetime
from zoneinfo import ZoneInfo

from django.conf import settings
from django.test import TestCase
from django.urls import reverse
from django.contrib.auth.models import User

from games.models import Game, Platform, Purchase

ZONEINFO = ZoneInfo(settings.TIME_ZONE)


class PathWorksTest(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_superuser(
            username="testuser", email="test@example.com", password="testpass"
        )
        self.client.force_login(self.user)
        self.platform = Platform.objects.create(name="Test Platform", icon="test")
        self.game = Game.objects.create(name="Test Game", platform=self.platform)
        self.purchase = Purchase.objects.create(
            date_purchased=datetime(2022, 9, 26, 14, 58, tzinfo=ZONEINFO),
            platform=self.platform,
        )
        self.purchase.games.add(self.game)

    def test_index_redirects_to_tracker(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)

    def test_tracker_page_returns_200(self):
        response = self.client.get("/tracker/", follow=True)
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
