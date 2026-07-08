"""Parity guard: every clickable sort header points at a key the backend knows.

A header's ``sort_key`` (set on a ``Column`` in a list view) must exist in that
view's ``*_SORTS`` map — otherwise clicking it produces an "unknown sort field"
warning instead of sorting. This renders each list view and asserts every sort
key appearing in the header links is a valid map key, catching label/key drift
in CI (mirrors the parity tests in tests/test_sorting.py).
"""

import re
from datetime import datetime
from urllib.parse import unquote
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from games.models import Device, Game, PlayEvent, Platform, Purchase
from games.sorting import (
    DEVICE_SORTS,
    GAME_SORTS,
    PLATFORM_SORTS,
    PLAYEVENT_SORTS,
    PURCHASE_SORTS,
    SESSION_SORTS,
)

ZONEINFO = ZoneInfo(settings.TIME_ZONE)


def _header_sort_keys(html: str) -> set[str]:
    """All sort keys referenced by the rendered table header links."""
    thead = html.split("<thead")[1].split("</thead>")[0]
    keys: set[str] = set()
    for value in re.findall(r"[?&;]sort=([^\"&]*)", thead):
        for token in unquote(value).split(","):
            token = token.strip().lstrip("-")
            if token:
                keys.add(token)
    return keys


class SortHeaderParityTest(TestCase):
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

    def _assert_parity(self, url_name: str, sort_map: dict) -> None:
        response = self.client.get(reverse(url_name))
        self.assertEqual(response.status_code, 200)
        keys = _header_sort_keys(response.content.decode())
        self.assertTrue(keys, f"{url_name} rendered no sortable headers")
        unknown = keys - set(sort_map)
        self.assertEqual(unknown, set(), f"{url_name} headers use unknown keys")

    def test_games_headers_match_map(self):
        self._assert_parity("games:list_games", GAME_SORTS)

    def test_sessions_headers_match_map(self):
        self._assert_parity("games:list_sessions", SESSION_SORTS)

    def test_purchases_headers_match_map(self):
        self._assert_parity("games:list_purchases", PURCHASE_SORTS)

    def test_playevents_headers_match_map(self):
        PlayEvent.objects.create(game=self.game)
        self._assert_parity("games:list_playevents", PLAYEVENT_SORTS)

    def test_devices_headers_match_map(self):
        Device.objects.create(name="Test Device")
        self._assert_parity("games:list_devices", DEVICE_SORTS)

    def test_platforms_headers_match_map(self):
        self._assert_parity("games:list_platforms", PLATFORM_SORTS)
