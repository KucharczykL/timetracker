"""Every data table's Actions column must hold strict maximum priority.

<responsive-table> keeps two columns no matter how narrow the region gets: the
row header, and the one that sorts last in drop order — highest priority,
leftmost among ties. That second slot is what keeps a row actionable on a
phone, but the element has no notion of "actions": it protects a position in
the priority order, and only the values declared here put Actions in it.

So this is the contract that turns that coincidence into a guarantee. Give a
column a priority at or above Actions' and the actions become droppable again
with nothing else failing — this test is what fails.
"""

import html
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from devices import create_device
from django.conf import settings
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from historical_playtime_rows import record_row
from session_rows import session_row

from common.components import Column, Span, StyledTable, make_row
from games.models import Game, Platform, Playthrough, Purchase

ZONEINFO = ZoneInfo(settings.TIME_ZONE)
BASE = datetime(2024, 5, 1, 12, 0, tzinfo=ZONEINFO)

_THEAD = re.compile(r"<thead.*?</thead>", re.DOTALL)
_HEADER_CELL = re.compile(r"<th\b(?P<attributes>[^>]*)>(?P<body>.*?)</th>", re.DOTALL)
_PRIORITY = re.compile(r'data-priority="(\d+)"')
_TAG = re.compile(r"<[^>]+>")

type HeaderPolicy = tuple[str, int]  # ("Actions", 4)


def _label(body: str) -> str:
    """The column label out of a header cell's inner markup.

    Its first text run: a sortable header wraps the label in a link and may
    append an indicator arrow and a rank badge, and the badge's digit would
    otherwise land in the label.
    """
    for chunk in _TAG.split(body):
        text = html.unescape(chunk).strip()
        if text:
            return text
    return ""


def header_policies(markup: str) -> list[list[HeaderPolicy]]:
    """Every data table's (label, priority) headers, one list per table.

    Read back out of the rendered page rather than off the view's ``Column``
    lists: most of them are built inside the view function, and the header
    cell is where the priority actually reaches the element.
    """
    tables = []
    for thead in _THEAD.findall(markup):
        policies: list[HeaderPolicy] = []
        for cell in _HEADER_CELL.finditer(thead):
            priority = _PRIORITY.search(cell["attributes"])
            # No data-priority: not a data table, so nothing drops.
            if not priority:
                continue
            policies.append((_label(cell["body"]), int(priority.group(1))))
        if policies:
            tables.append(policies)
    return tables


class RowMenuSlotPriorityTest(SimpleTestCase):
    """The slot's counterpart to the contract above.

    A table whose acts live in the row's menu declares no ``Actions`` column,
    so ``assert_actions_dominates`` exempts it — by design. The rank is
    computed instead of declared, and this is what holds the computation to
    the same promise: the slot outranks every column, so the element drops it
    last and a phone keeps the acts.
    """

    def test_the_slot_outranks_every_declared_column(self) -> None:
        markup = str(
            StyledTable(
                columns=[
                    Column("Name", shrinkable=True),
                    Column("Day", priority=5),
                    Column("Duration", priority=3),
                ],
                rows=[make_row("Hades", "Monday", "2 h", menu=Span()["acts"])],
                data_table=True,
                caption="Sessions",
            )
        )
        tables = header_policies(markup)
        self.assertEqual(len(tables), 1)
        priorities = [priority for _, priority in tables[0]]
        self.assertEqual(priorities[-1], max(priorities))
        self.assertGreater(priorities[-1], max(priorities[:-1]))


class ActionsColumnPriorityTest(TestCase):
    """Renders every page carrying a data table and checks each one."""

    def setUp(self) -> None:
        user = User.objects.create_superuser(username="tester", password="secret")
        self.client.force_login(user)
        library = user.library
        platform = Platform.objects.create(library=library, name="PC", icon="pc")
        self.game = Game.objects.create(
            library=library, name="A Game", platform=platform
        )
        device = create_device(library=library, name="Desktop", type="PC")
        session_row(
            self.game, device=device, started_at=BASE, ended_at=BASE.replace(hour=14)
        )
        purchase = Purchase.objects.create(
            library=library,
            platform=platform,
            date_purchased=BASE,
            price=10,
            price_currency="USD",
        )
        purchase.games.add(self.game)
        #: The section draws a table only with a row.
        record_row([Playthrough.objects.get(player_game__game=self.game)])

    def assert_actions_dominates(self, url: str) -> None:
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        tables = header_policies(response.content.decode())
        self.assertTrue(tables, f"{url} rendered no data table")
        for policies in tables:
            actions = [priority for label, priority in policies if label == "Actions"]
            # Exempt: a table whose acts are in the row menu slot, whose rank
            # `RowMenuSlotPriorityTest` holds, or one with no acts at all.
            if not actions:
                continue
            others = [priority for label, priority in policies if label != "Actions"]
            self.assertGreater(
                actions[0],
                max(others),
                f"{url}: Actions ({actions[0]}) does not outrank every other "
                f"column in {policies} — the narrowest fit may drop it",
            )

    def test_list_pages(self) -> None:
        for url_name in (
            "games:list_sessions",
            "games:list_games",
            "games:list_purchases",
            "games:list_playthroughs",
            "games:list_historical_playtime",
            "games:list_devices",
            "games:list_platforms",
        ):
            with self.subTest(url_name=url_name):
                self.assert_actions_dominates(reverse(url_name))

    def test_game_detail_tables(self) -> None:
        self.assert_actions_dominates(self.game.get_absolute_url())
