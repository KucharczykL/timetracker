"""Rendered-HTML assertions for pages converted to the Python layout/components.

These go beyond `test_paths_return_200`: they assert that the `Page()` document
wrapper and the Python component bodies emit the right structure, and — most
importantly — that nothing is double-escaped (the recurring failure mode when a
`SafeText` loses its safe marker and renders as `&lt;tag&gt;`).
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from games.models import Game, GameStatusChange, Platform, Purchase, Session

ZONEINFO = ZoneInfo(settings.TIME_ZONE)

# If any of these appear in output, a SafeText lost its safe marker somewhere.
_ESCAPED_TAG_MARKERS = [
    "&lt;a",
    "&lt;div",
    "&lt;span",
    "&lt;button",
    "&lt;input",
    "&lt;li",
]


class RenderedPagesTest(TestCase):
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
        self.session = Session.objects.create(
            game=self.game,
            timestamp_start=datetime(2022, 9, 26, 15, 0, tzinfo=ZONEINFO),
            timestamp_end=datetime(2022, 9, 26, 16, 0, tzinfo=ZONEINFO),
        )

    def get(self, url_name, *args):
        return self.client.get(reverse(url_name, args=args), follow=True)

    def assertNoEscapedTags(self, html):
        for marker in _ESCAPED_TAG_MARKERS:
            self.assertNotIn(
                marker, html, f"Found double-escaped markup ({marker!r}) in output"
            )

    # --- layout wrapper ------------------------------------------------------

    def test_page_layout_wrapper(self):
        """A converted page is wrapped in the full Page() document."""
        html = self.get("games:list_playevents").content.decode()
        for marker in [
            "<!DOCTYPE html>",
            "<nav",
            'id="main-container"',
            'id="global-modal-container"',
            "toastStore()",
            "</html>",
        ]:
            self.assertIn(marker, html)
        self.assertIn("Timetracker - Manage play events", html)

    # --- list pages ----------------------------------------------------------

    def test_list_pages_render_table_unescaped(self):
        for url_name in [
            "games:list_games",
            "games:list_purchases",
            "games:list_sessions",
            "games:list_platforms",
            "games:list_devices",
            "games:list_playevents",
        ]:
            with self.subTest(url_name=url_name):
                html = self.get(url_name).content.decode()
                self.assertIn("<table", html)
                self.assertNoEscapedTags(html)

    def test_session_list_keeps_inline_edit_attributes(self):
        html = self.get("games:list_sessions").content.decode()
        self.assertIn(f"session-row-{self.session.pk}", html)
        self.assertIn("device-changed from:body", html)

    # --- generic forms -------------------------------------------------------

    def test_generic_form_pages(self):
        for url_name in ["games:add_device", "games:add_platform"]:
            with self.subTest(url_name=url_name):
                html = self.get(url_name).content.decode()
                self.assertIn("csrfmiddlewaretoken", html)
                self.assertIn("<form", html)
                self.assertIn('type="submit"', html)
                self.assertNoEscapedTags(html)

    # --- specialized forms ---------------------------------------------------

    def test_add_game_form(self):
        html = self.get("games:add_game").content.decode()
        self.assertIn("add_game.js", html)
        self.assertIn("submit_and_redirect", html)
        self.assertIn("Submit &amp; Create Purchase", html)  # & correctly escaped
        self.assertNoEscapedTags(html)

    def test_add_purchase_form(self):
        html = self.get("games:add_purchase").content.decode()
        self.assertIn("add_purchase.js", html)
        self.assertIn("Submit &amp; Create Session", html)
        self.assertIn("<tr>", html)
        self.assertNoEscapedTags(html)

    def test_add_session_form_has_timestamp_helpers(self):
        html = self.get("games:add_session").content.decode()
        self.assertIn("add_session.js", html)
        for marker in [
            "Set to now",
            "Toggle text",
            "Copy start value to end",
            "Copy end value to start",
            'data-target="timestamp_start"',
            'data-type="now"',
            'hx-boost="false"',
        ]:
            self.assertIn(marker, html)
        self.assertNoEscapedTags(html)

    # --- detail pages --------------------------------------------------------

    def test_view_game(self):
        html = self.get("games:view_game", self.game.id).content.decode()
        for marker in [
            'id="game-info"',
            "font-bold font-serif",
            self.game.name,
            "Total hours played",  # stat popover tooltip
            'id="popover-hours"',
            "Original year",
            "Status",
            "Played",
            "Platform",
            'id="history-container"',
            "status-changed from:body",
            "createPlayEvent",  # the played-row Alpine dropdown script
            'hx-target="#global-modal-container"',  # delete trigger
            "Purchases",
            "Sessions",
            "Play Events",
            "History",
        ]:
            self.assertIn(marker, html)
        self.assertNoEscapedTags(html)
        self.assertEqual(html.count("<div"), html.count("</div>"))

    def test_view_game_empty_sections(self):
        """A game with no sessions/purchases/etc shows the empty messages."""
        lonely = Game.objects.create(name="Lonely Game", platform=self.platform)
        html = self.get("games:view_game", lonely.id).content.decode()
        for marker in [
            "No purchases yet.",
            "No sessions yet.",
            "No play events yet.",
        ]:
            self.assertIn(marker, html)
        self.assertNoEscapedTags(html)

    # --- HTMX fragments ------------------------------------------------------

    def test_delete_game_confirmation_modal(self):
        html = self.get("games:delete_game_confirmation", self.game.id).content.decode()
        # A fragment (no full-page layout).
        self.assertNotIn("<!DOCTYPE html>", html)
        self.assertIn('id="delete-game-confirmation-modal"', html)
        self.assertIn("hx-post", html)
        self.assertIn(self.game.name, html)
        self.assertIn("session(s)", html)  # seeded session
        self.assertIn("purchase(s)", html)  # seeded purchase
        self.assertNoEscapedTags(html)

    def test_refund_confirmation_modal(self):
        html = self.get(
            "games:refund_purchase_confirmation", self.purchase.id
        ).content.decode()
        self.assertIn('id="refund-confirmation-modal"', html)
        self.assertIn(f"#purchase-row-{self.purchase.id}", html)
        self.assertIn("Refund", html)
        self.assertNoEscapedTags(html)

    def test_session_row_fragment_via_htmx(self):
        # The inline "finish session" endpoint returns a <tr> fragment.
        resp = self.client.get(
            reverse("games:list_sessions_end_session", args=[self.session.id]),
            HTTP_HX_REQUEST="true",
        )
        html = resp.content.decode()
        self.assertTrue(html.lstrip().startswith("<tr"))
        self.assertIn(self.game.name, html)
        self.assertNoEscapedTags(html)

    # --- statuschange --------------------------------------------------------

    def test_statuschange_list_and_delete(self):
        change = GameStatusChange.objects.create(
            game=self.game,
            new_status="f",
            timestamp=self.session.timestamp_start,
        )
        list_html = self.get("games:list_statuschanges").content.decode()
        self.assertIn("<table", list_html)
        self.assertIn(self.game.name, list_html)
        self.assertNoEscapedTags(list_html)

        confirm_html = self.get("games:delete_statuschange", change.id).content.decode()
        self.assertIn(
            "Are you sure you want to delete this status change?", confirm_html
        )
        self.assertIn("Delete", confirm_html)
        self.assertIn("Cancel", confirm_html)
        self.assertNoEscapedTags(confirm_html)

    # --- login ---------------------------------------------------------------

    def test_login_page(self):
        from django.test import Client

        anon = Client()  # unauthenticated
        html = anon.get(reverse("login")).content.decode()
        for marker in [
            "<!DOCTYPE html>",  # full Page() layout
            "Please log in to continue",
            "csrfmiddlewaretoken",
            'type="submit"',
            'value="Login"',
            "</html>",
        ]:
            self.assertIn(marker, html)
        self.assertIn("Timetracker - Login", html)
        self.assertNoEscapedTags(html)

    # --- stats ---------------------------------------------------------------

    def test_stats_alltime(self):
        html = self.get("games:stats_alltime").content.decode()
        for marker in [
            'id="year-picker-input"',
            "All-time stats",
            "responsive-table",
            "Playtime",
            "Purchases",
            "Games by playtime",
            "Platforms by playtime",
        ]:
            self.assertIn(marker, html)
        self.assertNoEscapedTags(html)
        self.assertEqual(html.count("<table"), html.count("</table>"))

    def test_stats_by_year(self):
        year = self.session.timestamp_start.year
        html = self.get("games:stats_by_year", year).content.decode()
        # The seeded game/session/purchase should surface in the year view.
        self.assertIn("Playtime per month", html)
        self.assertIn(self.game.name, html)
        self.assertNoEscapedTags(html)
        self.assertEqual(html.count("<table"), html.count("</table>"))

    def test_view_purchase(self):
        html = self.get("games:view_purchase", self.purchase.id).content.decode()
        for marker in [
            "dark:text-white max-w-sm",
            "font-bold font-serif",
            "Owned on",
            "Price per game:",
            "decoration-dotted underline",
            "Games included in this purchase:",
            "<ul>",
            "<li>",
        ]:
            self.assertIn(marker, html)
        self.assertNoEscapedTags(html)
        # The Python builder emits well-formed, balanced markup.
        self.assertEqual(html.count("<div"), html.count("</div>"))
