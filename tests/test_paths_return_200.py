import os
from datetime import datetime
from zoneinfo import ZoneInfo

import django
from django.test import TestCase
from django.urls import reverse

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "timetracker.settings")
django.setup()
from django.conf import settings

from games.models import Game, Platform, Purchase, Session

ZONEINFO = ZoneInfo(settings.TIME_ZONE)


class PathWorksTest(TestCase):
    def setUp(self) -> None:
        pl = Platform(name="Test Platform")
        pl.save()
        g = Game(name="The Test Game")
        g.save()
        p = Purchase(
            games=[e],
            platform=pl,
            date_purchased=datetime(2022, 9, 26, 14, 58, tzinfo=ZONEINFO),
        )
        p.save()
        s = Session(
            purchase=p,
            timestamp_start=datetime(2022, 9, 26, 14, 58, tzinfo=ZONEINFO),
            timestamp_end=datetime(2022, 9, 26, 17, 38, tzinfo=ZONEINFO),
        )
        s.save()
        self.testSession = s
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
        url = reverse("view_game", args=[1])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_edit_game_returns_200(self):
        url = reverse("edit_game", args=[1])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_list_sessions_returns_200(self):
        url = reverse("list_sessions")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
