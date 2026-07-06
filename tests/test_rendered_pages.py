"""Rendered-HTML assertions for pages converted to the Python layout/components.

These go beyond `test_paths_return_200`: they assert that the `Page()` document
wrapper and the Python component bodies emit the right structure, and — most
importantly — that nothing is double-escaped (the recurring failure mode when a
`SafeText` loses its safe marker and renders as `&lt;tag&gt;`).
"""

from datetime import datetime
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from games.models import Game, GameStatusChange, Platform, Purchase, Session

ZONEINFO = ZoneInfo(settings.TIME_ZONE)

# Elements with no end tag — must not be pushed onto the ancestry stack.
_VOID_ELEMENTS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


class _ContentContainerAncestry(HTMLParser):
    """For each target tag, record the nearest ``max-w-7xl`` ancestor *outside*
    ``<nav>`` — the page-content container. The navbar has its own ``max-w-7xl``
    div, so a flat "``max-w-7xl`` appears before X" string assertion is vacuous;
    only real ancestry proves the filter tiers sit in the content container
    (issue #313).
    """

    def __init__(self, target_tags: list[str]) -> None:
        super().__init__(convert_charrefs=True)
        self.target_tags = set(target_tags)
        # (tag, container_id or None) per open element.
        self._stack: list[tuple[str, int | None]] = []
        self._container_count = 0
        # target tag -> container id of its nearest content-container ancestor
        # (None = no such ancestor), first occurrence only.
        self.found: dict[str, int | None] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        ancestor_container = next(
            (
                container_id
                for _, container_id in reversed(self._stack)
                if container_id is not None
            ),
            None,
        )
        if tag in self.target_tags and tag not in self.found:
            self.found[tag] = ancestor_container
        container_id = None
        classes = (dict(attrs).get("class") or "").split()
        inside_nav = tag == "nav" or any(
            open_tag == "nav" for open_tag, _ in self._stack
        )
        if "max-w-7xl" in classes and not inside_nav:
            self._container_count += 1
            container_id = self._container_count
        if tag not in _VOID_ELEMENTS:
            self._stack.append((tag, container_id))

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index][0] == tag:
                del self._stack[index:]
                break


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
        """The games list view passes no scripts= argument; the quick bar's
        components declare their JS and Page() collects it."""
        html = self.get("games:list_games").content.decode()
        self.assertIn("js/dist/elements/quick-filter-bar.js", html)
        self.assertIn("js/dist/elements/search-select.js", html)
        self.assertIn("js/dist/elements/drop-down.js", html)

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

    def test_head_scripts_are_not_escaped(self):
        """Inline <script> bodies in the head must render as real markup, not
        HTML-escaped text (the f-string→component conversion regressed this:
        <script> is a raw-text element, so its body is emitted verbatim)."""
        html = self.get("games:list_playevents").content.decode()
        # No script tag should appear escaped anywhere on the page.
        self.assertNotIn("&lt;script", html)
        # Inline JS keeps its quotes (escaping would yield &#x27;).
        self.assertIn("htmx.config.scrollBehavior = 'smooth';", html)
        self.assertNotIn("&#x27;smooth&#x27;", html)
        # Correct charset markup, not <meta name="charset">.
        self.assertIn('<meta charset="utf-8"', html)
        # A single, un-escaped django-messages JSON block.
        self.assertEqual(html.count('id="django-messages"'), 1)

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

    def test_session_list_row_has_id_and_device_selector(self):
        html = self.get("games:list_sessions").content.decode()
        self.assertIn(f"session-row-{self.session.pk}", html)
        # The device selector stays (vanilla-fetch custom element); the htmx
        # row-refresh wiring is gone.
        self.assertIn(f"session-{self.session.pk}-device", html)
        self.assertNotIn("device-changed from:body", html)

    def test_list_page_filter_tiers_share_content_container(self):
        """Issues #313/#315: every list page renders exactly one filter tier —
        the quick bar — inside the same non-navbar ``max-w-7xl`` content
        container (``ContentContainer``) as its table, and no flat filter-bar
        at all (the flat-bar layer was deleted in the #315 rollout)."""
        for url_name in (
            "games:list_games",
            "games:list_sessions",
            "games:list_purchases",
            "games:list_playevents",
            "games:list_devices",
            "games:list_platforms",
        ):
            with self.subTest(url_name=url_name):
                html = self.get(url_name).content.decode()
                self.assertNotIn("<filter-bar", html)
                ancestry = _ContentContainerAncestry(["quick-filter-bar", "table"])
                ancestry.feed(html)
                self.assertEqual(
                    set(ancestry.found),
                    {"quick-filter-bar", "table"},
                    f"expected quick bar + table on {url_name}",
                )
                self.assertNotIn(
                    None,
                    ancestry.found.values(),
                    f"element(s) outside the content container: {ancestry.found}",
                )
                self.assertEqual(
                    len(set(ancestry.found.values())),
                    1,
                    f"tiers sit in different containers: {ancestry.found}",
                )

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
        self.assertIn('name="submit_and_redirect"', html)
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

    def test_played_row_count_link_is_a_single_anchor(self):
        """The 'N times' count control is one styled <a> (ControlButton href
        mode), not a <button> nested inside an <a> (invalid HTML)."""
        game = Game.objects.create(name="Anchor Game", platform=self.platform)
        html = self.get("games:view_game", game.id).content.decode()
        row = html[html.index("<play-event-row") :]
        count_at = row.index("data-count")
        control = row[row.rindex("<a", 0, count_at) : row.index("</a>", count_at)]
        self.assertNotIn("<button", control)
        # the anchor itself carries the outline-toggle look and its shape class
        self.assertIn("border-gray-200", control)
        self.assertIn("rounded-s-lg", control)

    def test_played_row_label_is_one_flex_item_and_count_is_a_prop(self):
        """'N times' is one prose phrase, so it must be a single flex item:
        the count anchor is inline-flex, and flex layout drops whitespace-only
        text between items — sibling span + " times" rendered as "0times".
        The initial count also crosses to play-event-row.ts as the count=""
        prop; the data-count span is a write-only display slot."""
        game = Game.objects.create(name="Prose Game", platform=self.platform)
        html = self.get("games:view_game", game.id).content.decode()
        row = html[html.index("<play-event-row") :]
        host_tag = row[: row.index(">") + 1]
        self.assertIn('count="0"', host_tag)
        self.assertIn('<span><span data-count="">0</span> times</span>', row)

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

    def test_session_list_renders_session_actions_element(self):
        # Finish/reset are now driven by the <session-actions> custom element
        # (PATCH /api/session/<id> + client-side row swap), not POST/confirm pages.
        html = self.get("games:list_sessions").content.decode()
        self.assertIn("<session-actions", html)
        self.assertIn(f'api-url="/api/session/{self.session.id}"', html)
        self.assertNoEscapedTags(html)

    def test_finish_reset_buttons_only_shown_for_running_sessions(self):
        running = Session.objects.create(
            game=self.game,
            timestamp_start=datetime(2020, 1, 1, 10, 0, tzinfo=ZONEINFO),
        )
        html = self.get("games:list_sessions").content.decode()
        # The running session's row exposes finish + reset; the finished
        # self.session row exposes neither (its <session-actions> is_open=false).
        self.assertIn("data-reset-modal", html)  # only the running row has one
        self.assertIn(f'<session-actions session-id="{running.id}"', html)
        self.assertIn('is-open="true"', html)
        self.assertIn('is-open="false"', html)

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
            ">Login<",  # ControlButton submit (was an <input value="Login">)
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
            # ContentContainer bakes the width classes; caller class appends.
            "w-full max-w-7xl self-center dark:text-white",
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
            'name="quick-date_purchased-min" id="quick-date_purchased-min" '
            'value="2024-01-01"',
            html,
        )
        self.assertIn(
            'name="quick-date_purchased-max" id="quick-date_purchased-max" '
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
            'name="quick-date_purchased-min" id="quick-date_purchased-min" '
            'value="2024-06-15"',
            html,
        )
        self.assertIn(
            'name="quick-date_purchased-max" id="quick-date_purchased-max" value=""',
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

    def test_malformed_json_filter_warns_and_falls_back_to_unfiltered(self):
        """Bad JSON raises FilterError; the view warns-and-ignores → full list,
        a warning toast, and no 500."""
        response = self._get(raw_filter="this is not json")
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        # All three purchases are present, same as the unfiltered baseline.
        self.assertIn("EARLY-MARKER", html)
        self.assertIn("MID-MARKER", html)
        self.assertIn("LATE-MARKER", html)
        # A warning toast is queued (rendered into the django-messages blob).
        self.assertIn("Ignored invalid filter", html)

    def test_semantically_invalid_filter_warns_and_falls_back(self):
        """Parseable JSON but a build-time-invalid filter (BETWEEN without value2)
        must warn-and-ignore, not 500."""
        response = self._get(
            {"date_purchased": {"value": "2024-01-01", "modifier": "BETWEEN"}}
        )
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("EARLY-MARKER", html)
        self.assertIn("MID-MARKER", html)
        self.assertIn("LATE-MARKER", html)
        self.assertIn("Ignored invalid filter", html)


class GameListSessionFilterBoundaryTest(TestCase):
    """The games list is the only view that calls to_q() a SECOND time, on the
    nested session_filter (games/views/game.py). These tests drive that path at
    the view level: a valid session_filter narrows and renders 200; an invalid
    one warns-and-ignores rather than 500-ing."""

    def setUp(self) -> None:
        from datetime import timedelta

        from django.utils import timezone

        self.user = User.objects.create_superuser(
            username="gamefilter", email="gf@example.com", password="testpass"
        )
        self.client.force_login(self.user)
        self.platform = Platform.objects.create(name="GFP", icon="gfp")
        self.played = Game.objects.create(name="PLAYED-MARKER", platform=self.platform)
        self.unplayed = Game.objects.create(
            name="UNPLAYED-MARKER", platform=self.platform
        )
        start = timezone.now()
        Session.objects.create(
            game=self.played,
            timestamp_start=start,
            timestamp_end=start + timedelta(hours=2),
            note="BOSS fight",
        )

    def _get(self, raw_filter):
        from django.urls import reverse

        return self.client.get(reverse("games:list_games"), {"filter": raw_filter})

    def test_valid_session_filter_narrows_at_view(self):
        """A valid session_filter renders 200 and narrows to games with a
        matching session — exercises game.py's second session_filter.to_q()."""
        import json

        response = self._get(
            json.dumps(
                {"session_filter": {"note": {"modifier": "INCLUDES", "value": "boss"}}}
            )
        )
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("PLAYED-MARKER", html)
        self.assertNotIn("UNPLAYED-MARKER", html)

    def test_invalid_session_filter_warns_and_falls_back(self):
        """An invalid nested session_filter warns-and-ignores, not 500."""
        import json

        response = self._get(
            json.dumps(
                {
                    "session_filter": {
                        "duration_total_hours": {"modifier": "BETWEEN", "value": 1}
                    }
                }
            )
        )
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("PLAYED-MARKER", html)
        self.assertIn("UNPLAYED-MARKER", html)
        self.assertIn("Ignored invalid filter", html)
