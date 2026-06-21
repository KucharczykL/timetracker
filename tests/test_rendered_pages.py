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
from django.utils import timezone

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

    # --- scripts auto-collected from component media (Phase 4) ---------------

    def test_list_page_auto_loads_widget_scripts(self):
        """The games list view passes no scripts= argument; the filter bar's
        components declare their JS and Page() collects it."""
        html = self.get("games:list_games").content.decode()
        self.assertIn("js/dist/elements/filter-bar.js", html)
        self.assertIn("js/dist/elements/search-select.js", html)

    def test_stats_page_auto_loads_datepicker(self):
        """YearPicker declares the datepicker UMD bundle as media; the stats
        view no longer hoists it by hand."""
        html = self.get("games:stats_alltime").content.decode()
        self.assertIn("js/datepicker.umd.js", html)

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
        self.assertIn("dist/add_game.js", html)
        self.assertIn("submit_and_redirect", html)
        self.assertIn("Submit &amp; Create Purchase", html)  # & correctly escaped
        self.assertIn("submit_and_create_session", html)
        self.assertIn("Submit &amp; Create Session", html)  # & correctly escaped
        # Fields self-style: label + control carry their own classes (no #add-form
        # / form CSS in input.css).
        self.assertIn("mb-2.5 text-sm font-medium text-heading", html)  # _LABEL_CLASS
        self.assertIn("bg-neutral-secondary-medium", html)  # INPUT_CLASS surface
        self.assertNoEscapedTags(html)

    def test_add_game_submit_and_create_session_redirects(self):
        response = self.client.post(
            reverse("games:add_game"),
            {
                "name": "New Session Game",
                "status": "u",
                "submit_and_create_session": "",
            },
        )
        game = Game.objects.get(name="New Session Game")
        self.assertRedirects(
            response,
            reverse("games:add_session_for_game", kwargs={"game_id": game.id}),
        )

    def test_form_errors_render_with_component_class(self):
        """Invalid submits re-render field errors via FormFields' own class, not
        Django's .errorlist (which no longer exists in the CSS)."""
        # Non-empty but invalid (name is required) so the form binds and
        # re-renders with errors — an empty {} POST is falsy and stays unbound.
        response = self.client.post(reverse("games:add_game"), {"status": "u"})
        html = response.content.decode()
        self.assertIn("bg-red-600", html)  # _FIELD_ERROR_CLASS
        self.assertNotIn('class="errorlist"', html)
        self.assertNoEscapedTags(html)

    def test_add_purchase_form(self):
        html = self.get("games:add_purchase").content.decode()
        self.assertIn("dist/add_purchase.js", html)
        self.assertIn("Submit &amp; Create Session", html)
        self.assertIn("<tr>", html)
        self.assertNoEscapedTags(html)

    def test_add_session_form_has_timestamp_helpers(self):
        html = self.get("games:add_session").content.decode()
        self.assertIn("session-timestamp-buttons", html)
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
            "<play-event-row",  # the played-row custom element
            'hx-target="#global-modal-container"',  # delete trigger
            "Purchases",
            "Sessions",
            "Play Events",
            "History",
        ]:
            self.assertIn(marker, html)
        self.assertNoEscapedTags(html)
        self.assertEqual(html.count("<div"), html.count("</div>"))

    def test_view_game_uses_play_event_row_element(self):
        game = Game.objects.create(name="Played Game", platform=self.platform)
        html = self.get("games:view_game", game.id).content.decode()
        self.assertIn("<play-event-row", html)
        self.assertIn('game-id="', html)
        self.assertNotIn("@@", html)  # token-replace hack gone
        self.assertNotIn("createPlayEvent", html)  # the old Alpine fn is gone

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
        # The inline "finish session" endpoint returns an in-place row swap
        # (<tr id="session-row-{pk}">) plus an OOB navbar-playtime update.
        resp = self.client.get(
            reverse("games:list_sessions_end_session", args=[self.session.id]),
            HTTP_HX_REQUEST="true",
        )
        html = resp.content.decode()
        self.assertTrue(html.lstrip().startswith("<tr"))
        self.assertIn(f'id="session-row-{self.session.id}"', html)
        self.assertIn('id="navbar-playtime"', html)
        self.assertIn('hx-swap-oob="true"', html)
        self.assertIn(self.game.name, html)
        self.assertNoEscapedTags(html)

    def test_reset_session_start_to_now_via_htmx(self):
        # The inline "reset start" endpoint sets timestamp_start to now and
        # returns an in-place row swap plus an OOB navbar update.
        running = Session.objects.create(
            game=self.game,
            timestamp_start=datetime(2020, 1, 1, 10, 0, tzinfo=ZONEINFO),
        )
        before = timezone.now()
        resp = self.client.get(
            reverse("games:list_sessions_reset_session_start", args=[running.id]),
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn(f'id="session-row-{running.id}"', body)
        self.assertIn('id="navbar-playtime"', body)
        self.assertNotIn("HX-Refresh", resp.headers)
        running.refresh_from_db()
        self.assertGreaterEqual(running.timestamp_start, before)

    def test_reset_session_start_redirects_without_htmx(self):
        running = Session.objects.create(
            game=self.game,
            timestamp_start=datetime(2020, 1, 1, 10, 0, tzinfo=ZONEINFO),
        )
        resp = self.client.get(
            reverse("games:list_sessions_reset_session_start", args=[running.id])
        )
        self.assertRedirects(resp, reverse("games:list_sessions"))

    def test_reset_button_only_shown_for_running_sessions(self):
        running = Session.objects.create(
            game=self.game,
            timestamp_start=datetime(2020, 1, 1, 10, 0, tzinfo=ZONEINFO),
        )
        html = self.get("games:list_sessions").content.decode()
        self.assertIn(
            reverse("games:list_sessions_reset_session_start", args=[running.id]),
            html,
        )
        self.assertNotIn(
            reverse("games:list_sessions_reset_session_start", args=[self.session.id]),
            html,
        )

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
            'name="username"',  # auth form fields rendered via FormFields
            'type="submit"',
            ">Login<",  # StyledButton submit (was an <input value="Login">)
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


class PurchaseListDateFilterTest(TestCase):
    """End-to-end: GET /tracker/purchase/list?filter=… narrows the rendered
    list and pre-fills the date inputs from the URL filter.

    Replaces the manual curl smoke that earlier verified the same path.
    """

    def setUp(self) -> None:
        import datetime

        self.user = User.objects.create_superuser(
            username="datetester", email="dt@example.com", password="testpass"
        )
        self.client.force_login(self.user)
        self.platform = Platform.objects.create(name="DateP", icon="datep")
        # Markers are placed on the Game name because LinkedPurchase renders
        # the linked game's name (purchase.name doesn't surface in the list row).
        early_game = Game.objects.create(name="EARLY-MARKER", platform=self.platform)
        mid_game = Game.objects.create(name="MID-MARKER", platform=self.platform)
        late_game = Game.objects.create(name="LATE-MARKER", platform=self.platform)
        self.early = Purchase.objects.create(
            platform=self.platform, date_purchased=datetime.date(2024, 1, 15)
        )
        self.early.games.add(early_game)
        self.mid = Purchase.objects.create(
            platform=self.platform,
            date_purchased=datetime.date(2024, 6, 15),
            date_refunded=datetime.date(2024, 7, 1),
        )
        self.mid.games.add(mid_game)
        self.late = Purchase.objects.create(
            platform=self.platform, date_purchased=datetime.date(2025, 1, 15)
        )
        self.late.games.add(late_game)

    def _get(self, filter_obj=None, raw_filter=None):
        import json

        from django.urls import reverse

        url = reverse("games:list_purchases")
        if raw_filter is not None:
            return self.client.get(url, {"filter": raw_filter})
        if filter_obj is not None:
            return self.client.get(url, {"filter": json.dumps(filter_obj)})
        return self.client.get(url)

    def test_unfiltered_lists_all_three(self):
        html = self._get().content.decode()
        self.assertEqual(html.count("EARLY-MARKER"), 1)
        self.assertEqual(html.count("MID-MARKER"), 1)
        self.assertEqual(html.count("LATE-MARKER"), 1)

    def test_date_purchased_between_narrows_and_prepopulates(self):
        """BETWEEN 2024-01-01..2024-12-31 → only early + mid; both date
        inputs pre-filled with the filter bounds."""
        response = self._get(
            {
                "date_purchased": {
                    "value": "2024-01-01",
                    "value2": "2024-12-31",
                    "modifier": "BETWEEN",
                }
            }
        )
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("EARLY-MARKER", html)
        self.assertIn("MID-MARKER", html)
        self.assertNotIn("LATE-MARKER", html)
        # Pre-populated date inputs round-trip the filter bounds.
        self.assertIn(
            'name="filter-date-purchased-min" id="filter-date-purchased-min" '
            'value="2024-01-01"',
            html,
        )
        self.assertIn(
            'name="filter-date-purchased-max" id="filter-date-purchased-max" '
            'value="2024-12-31"',
            html,
        )

    def test_date_purchased_greater_than_single_bound(self):
        """GREATER_THAN populates min only, leaves max blank."""
        response = self._get(
            {
                "date_purchased": {
                    "value": "2024-06-15",
                    "modifier": "GREATER_THAN",
                }
            }
        )
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertNotIn("EARLY-MARKER", html)
        self.assertNotIn("MID-MARKER", html)
        self.assertIn("LATE-MARKER", html)
        self.assertIn(
            'name="filter-date-purchased-min" id="filter-date-purchased-min" '
            'value="2024-06-15"',
            html,
        )
        self.assertIn(
            'name="filter-date-purchased-max" id="filter-date-purchased-max" value=""',
            html,
        )

    def test_date_refunded_not_null(self):
        response = self._get({"date_refunded": {"value": "", "modifier": "NOT_NULL"}})
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertNotIn("EARLY-MARKER", html)
        self.assertIn("MID-MARKER", html)
        self.assertNotIn("LATE-MARKER", html)

    def test_combined_dates_and_is_refunded(self):
        """date_purchased BETWEEN 2024 AND date_refunded NOT_NULL → only the
        mid purchase. Confirms AND-composition through the view layer."""
        response = self._get(
            {
                "date_purchased": {
                    "value": "2024-01-01",
                    "value2": "2024-12-31",
                    "modifier": "BETWEEN",
                },
                "date_refunded": {"value": "", "modifier": "NOT_NULL"},
            }
        )
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertNotIn("EARLY-MARKER", html)
        self.assertIn("MID-MARKER", html)
        self.assertNotIn("LATE-MARKER", html)

    def test_malformed_json_filter_falls_back_to_unfiltered(self):
        """parse_purchase_filter returns None on bad JSON → view ignores
        the filter and renders the full list (no 500)."""
        response = self._get(raw_filter="this is not json")
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        # All three purchases are present, same as the unfiltered baseline.
        self.assertIn("EARLY-MARKER", html)
        self.assertIn("MID-MARKER", html)
        self.assertIn("LATE-MARKER", html)
