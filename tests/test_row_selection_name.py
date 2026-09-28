"""Each selectable row shows its name in one clip.

`identityName` in `ts/elements/selectable-table.ts` names the row checkbox
from that clip; icon titles and tooltips beside it never reach the name.
"""

import html
import re

from devices import create_device
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from tracked_games import create_tracked_game

from games.models import Device, Platform

type RowName = str

_IDENTITY = re.compile(r"data-row-identity.*?</th>", re.DOTALL)
_CLIP = re.compile(r"<span data-truncated-clip[^>]*>([^<]*)</span>")


def _clipped_names(page: str) -> list[list[RowName]]:
    """Each row identity's clip texts."""
    return [
        [html.unescape(text) for text in _CLIP.findall(identity)]
        for identity in _IDENTITY.findall(page)
    ]


class RowSelectionNameTest(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(username="tester", password="pw")
        self.client.force_login(self.user)

    def _page(self, url_name: str) -> str:
        return self.client.get(reverse(url_name)).content.decode()

    def test_a_device_row_shows_its_name_in_one_clip(self) -> None:
        create_device(self.user.library, "Steam Deck", Device.HANDHELD)

        self.assertEqual(
            _clipped_names(self._page("games:list_devices")), [["Steam Deck"]]
        )

    def test_a_game_row_clips_its_name_apart_from_icon_and_tooltip(self) -> None:
        platform = Platform.objects.create(
            library=self.user.library, name="PC", icon="steam", group="PC"
        )
        create_tracked_game(
            self.user.library,
            "The Witness",
            platform=platform,
            sort_name="Witness, The",
        )

        self.assertEqual(
            _clipped_names(self._page("games:list_games")), [["The Witness"]]
        )
