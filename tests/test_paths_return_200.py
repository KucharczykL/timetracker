import os
from datetime import datetime
from zoneinfo import ZoneInfo

import django
from django.test import TestCase
from django.urls import reverse

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "timetracker.settings")
django.setup()
from django.conf import settings

from django.contrib.auth.models import User

from games.models import Game, Platform, Purchase, Session

ZONEINFO = ZoneInfo(settings.TIME_ZONE)


class PathWorksTest(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_superuser(
            username="testuser", email="test@example.com", password="testpass"
        )
        self.client.force_login(self.user)
        pl = Platform(name="Test Platform")
        pl.save()
        g = Game(name="The Test Game")
        g.save()
        p = Purchase(
            platform=pl,
            date_purchased=datetime(2022, 9, 26, 14, 58, tzinfo=ZONEINFO),
        )
        p.save()
        p.games.add(g)
        p.save()
        s = Session(
            game=g,
            timestamp_start=datetime(2022, 9, 26, 14, 58, tzinfo=ZONEINFO),
            timestamp_end=datetime(2022, 9, 26, 17, 38, tzinfo=ZONEINFO),
        )
        s.save()
        self.testSession = s
        self.testGame = g
        return super().setUp()

    def test_add_device_returns_200(self):
        url = reverse("add_device")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_add_platform_returns_200(self):
        url = reverse("add_platform")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_add_game_returns_200(self):
        url = reverse("add_game")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_add_purchase_returns_200(self):
        url = reverse("add_purchase")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_add_session_returns_200(self):
        url = reverse("add_session")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_edit_session_returns_200(self):
        id = self.testSession.id
        url = reverse("edit_session", args=[id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_view_game_returns_200(self):
        url = reverse("view_game", args=[self.testGame.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_edit_game_returns_200(self):
        url = reverse("edit_game", args=[self.testGame.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_list_sessions_returns_200(self):
        url = reverse("list_sessions")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
