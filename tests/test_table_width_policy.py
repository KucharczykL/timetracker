"""Cross-page contract for the data-table width policy.

The per-component behaviour lives in `test_components.py`; this asserts that
every page that renders a table of records actually opts in — a new list view
that forgets the gate is the failure this catches — and that the stats cards,
which render through the same component, stay out.
"""

import re
from datetime import datetime, timedelta
from uuid import uuid7
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from games.models import (
    Device,
    Game,
    GameStatusChange,
    Platform,
    PlayerGame,
    PlayEvent,
    Purchase,
    Session,
)

ZONEINFO = ZoneInfo(settings.TIME_ZONE)
BASE = datetime(2025, 3, 1, 10, 0, tzinfo=ZONEINFO)

# Every list page; each one's first column is a name that must self-clip.
LIST_PAGES = [
    "games:list_sessions",
    "games:list_games",
    "games:list_purchases",
    "games:list_playevents",
    "games:list_devices",
    "games:list_platforms",
]


def _regions(html: str) -> list[str]:
    """The table scroll wrappers: the divs carrying both the overflow class and
    the region role, matched attribute-order-independently. The toast container
    is also a region, but has no overflow class."""
    return [
        tag
        for tag in re.findall(r"<div\b[^>]*>", html)
        if "overflow-x-auto" in tag and 'role="region"' in tag
    ]


def _caption_text(html: str, caption_id: str) -> str | None:
    match = re.search(
        rf'<caption[^>]*\bid="{re.escape(caption_id)}"[^>]*>(.*?)</caption>',
        html,
        re.DOTALL,
    )
    return match.group(1).strip() if match else None


class DataTableGateTest(TestCase):
    user: User

    @classmethod
    def setUpTestData(cls) -> None:
        cls.user = User.objects.create_user(username="tester", password="pw")
        library = cls.user.library
        platform = Platform.objects.create(
            library=library, name="PC", icon="pc", group="PC"
        )
        device = Device.objects.create(library=library, name="Desktop", type="p")
        game = Game.objects.create(library=library, name="A Game", platform=platform)
        # setUpTestData runs at class scope, before the autouse fixture that
        # tracks a created game, so the games list would find nothing to clip.
        PlayerGame.objects.create(
            pk=uuid7(), library=library, game=game, tracked_at=timezone.now()
        )
        Session.objects.create(
            game=game,
            device=device,
            timestamp_start=BASE,
            timestamp_end=BASE + timedelta(hours=2),
        )
        purchase = Purchase.objects.create(
            platform=platform,
            date_purchased=BASE,
            price=10,
            price_currency="USD",
            library=library,
        )
        purchase.games.add(game)
        PlayEvent.objects.create(game=game, started=BASE, note="a note")
        GameStatusChange.objects.create(game=game, new_status="p", timestamp=BASE)

    def setUp(self) -> None:
        self.client.force_login(self.user)

    def _html(self, url_name: str) -> str:
        return self.client.get(reverse(url_name), follow=True).content.decode()

    def test_every_list_page_has_one_named_scroll_region(self) -> None:
        for url_name in LIST_PAGES:
            with self.subTest(page=url_name):
                html = self._html(url_name)
                regions = _regions(html)
                self.assertEqual(len(regions), 1, "expected exactly one table region")
                labelledby = re.search(r'aria-labelledby="([^"]+)"', regions[0])
                assert labelledby is not None, "region must be labelled"
                text = _caption_text(html, labelledby.group(1))
                self.assertTrue(text, "region's accessible name must be non-empty")

    def test_every_list_page_region_is_keyboard_reachable(self) -> None:
        for url_name in LIST_PAGES:
            with self.subTest(page=url_name):
                self.assertIn('tabindex="0"', _regions(self._html(url_name))[0])

    def test_every_list_page_mounts_one_responsive_table(self) -> None:
        """The priority-plus element wraps every list table's region; a new
        list view that forgets the data-table gate is the failure this
        catches."""
        for url_name in LIST_PAGES:
            with self.subTest(page=url_name):
                self.assertEqual(self._html(url_name).count("<responsive-table"), 1)

    def test_first_column_self_clips_on_every_list_page(self) -> None:
        """A pinned single-line first column with no cap can be arbitrarily
        wide, so every list page routes its first cell through TruncatedText."""
        for url_name in LIST_PAGES:
            with self.subTest(page=url_name):
                body = self._html(url_name).split("<tbody", 1)[1]
                first_cell = body.split("</th>", 1)[0]
                self.assertIn("<truncated-text", first_cell)

    def test_stats_cards_are_not_data_tables(self) -> None:
        """They are 2-column cards with no scroll region; their value cells wrap
        by design, and a one-line rule would turn that into hidden overflow."""
        html = self.client.get(
            reverse("games:stats_alltime"), follow=True
        ).content.decode()
        self.assertIn("<table", html)
        self.assertEqual(_regions(html), [])
        self.assertNotIn("<caption", html)
        self.assertNotIn("<responsive-table", html)

    def test_playevents_note_column_may_wrap(self) -> None:
        """Free text has no natural width; on one line a long note would widen
        the table past anything the other columns could reclaim."""
        html = self._html("games:list_playevents")
        header_cells = html.split("<thead", 1)[1].split("</thead>", 1)[0].split("<th")
        note_header = next(cell for cell in header_cells if ">Note<" in cell)
        self.assertNotIn("whitespace-nowrap", note_header)


@pytest.mark.django_db(transaction=True)
def test_refunded_row_fragment_keeps_the_tables_policy(client, owned_user) -> None:
    """The refund re-renders one row alone.

    A fragment built without the column list renders under a different width
    policy than the rows it lands between.
    """
    #: Out of the TestCase, because the refund dispatches.
    client.force_login(owned_user)
    library = owned_user.library
    platform = Platform.objects.create(
        library=library, name="PC", icon="pc", group="PC"
    )
    game = Game.objects.create(library=library, name="A Game", platform=platform)
    purchase = Purchase.objects.create(
        platform=platform,
        date_purchased=BASE,
        price=10,
        price_currency="USD",
        library=library,
    )
    purchase.games.add(game)

    response = client.post(reverse("games:refund_purchase", args=[purchase.pk]))

    row = response.content.decode()
    assert "max-md:max-w-0" in row
    assert "whitespace-nowrap" in row.split("<td", 1)[1]
