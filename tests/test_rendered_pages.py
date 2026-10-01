"""Rendered-HTML assertions for pages converted to the Python layout/components.

These go beyond `test_paths_return_200`: they assert that the `Page()` document
wrapper and the Python component bodies emit the right structure, and — most
importantly — that nothing is double-escaped (the recurring failure mode when a
`SafeText` loses its safe marker and renders as `&lt;tag&gt;`).
"""

import re
from datetime import datetime, timedelta
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

import pytest
from calendar_days import library_noon
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from entries import record_entry
from graphs import default_graph
from purchases import record_purchase, refund_purchase
from pytest_django.asserts import assertRedirects
from session_rows import session_row, timed_row, tracked_run

from common.components.primitives import _FIELD_ERROR_CLASS, control_button_class
from games.models import Game, LegacyPurchase, Platform, PlayerSession
from games.reads.playtime import game_playtime
from timetracker.temporal import TemporalValue

ZONEINFO = ZoneInfo("Europe/Prague")

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
        self.platform = Platform.objects.create(
            library=self.user.library, name="Test Platform", icon="steam"
        )
        self.game = Game.objects.create(
            library=self.user.library, name="Test Game", platform=self.platform
        )
        self.purchase = LegacyPurchase.objects.create(
            library=self.user.library,
            price_currency="CZK",
            date_purchased=datetime(2022, 9, 26, 14, 58, tzinfo=ZONEINFO),
            platform=self.platform,
        )
        self.purchase.games.add(self.game)
        #: The projection reads this one.
        record_purchase(
            record_entry(
                self.user.library,
                default_graph(self.game, self.user.library).release,
            )
        )
        self.session = timed_row(
            tracked_run(self.user.library, self.game),
            datetime(2022, 9, 26, 15, 0, tzinfo=ZONEINFO),
            datetime(2022, 9, 26, 16, 0, tzinfo=ZONEINFO),
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

    def test_stats_page_does_not_load_datepicker_bundle(self):
        """The in-house YearPicker needs no vendored datepicker bundle."""
        html = self.get("games:stats_alltime").content.decode()
        self.assertNotIn("js/" + "date" + "picker" + "." + "umd" + "." + "js", html)

    # --- layout wrapper ------------------------------------------------------

    def test_page_layout_wrapper(self):
        """A converted page is wrapped in the full Page() document."""
        html = self.get("games:list_playthroughs").content.decode()
        for marker in [
            "<!DOCTYPE html>",
            "<nav",
            'id="main-container"',
            '<toast-stack role="region" aria-label="Notifications" aria-live="polite"',
            f'action-class="{control_button_class(variant="ghost")}"',
            "</html>",
        ]:
            self.assertIn(marker, html)
        self.assertIn("Timetracker - Manage playthroughs", html)
        # The page shell carries the horizontal gutter (issue #413) so content
        # stays off the viewport edges below the max-width cap.
        self.assertRegex(html, r'id="main-container"[^>]*class="[^"]*\bpx-4\b')

    def test_head_scripts_are_not_escaped(self):
        """Inline <script> bodies in the head must render as real markup, not
        HTML-escaped text (the f-string→component conversion regressed this:
        <script> is a raw-text element, so its body is emitted verbatim)."""
        html = self.get("games:list_playthroughs").content.decode()
        # No script tag should appear escaped anywhere on the page.
        self.assertNotIn("&lt;script", html)
        # Inline JS keeps its quotes (escaping would yield &#x27;).
        self.assertIn("document.addEventListener('DOMContentLoaded'", html)
        self.assertNotIn("&#x27;DOMContentLoaded&#x27;", html)
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
            "games:list_playthroughs",
        ]:
            with self.subTest(url_name=url_name):
                html = self.get(url_name).content.decode()
                self.assertIn("<table", html)
                self.assertNoEscapedTags(html)

    def test_session_list_row_has_id_and_device_selector(self):
        html = self.get("games:list_sessions").content.decode()
        self.assertIn(f"session-row-{self.session.pk}", html)
        # The device selector stays (vanilla-fetch custom element); no row
        # refreshes itself.
        self.assertIn(f"session-{self.session.pk}-device", html)

    def test_list_page_filter_tiers_share_content_container(self):
        """Every list page renders exactly one filter tier —
        the quick bar — inside the same non-navbar ``max-w-7xl`` content
        container (``ContentContainer``) as its table, and no flat
        filter-bar at all."""
        for url_name in (
            "games:list_games",
            "games:list_sessions",
            "games:list_purchases",
            "games:list_playthroughs",
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
        self.assertIn("submit_and_add_to_library", html)
        self.assertIn("Submit &amp; Add to library", html)  # & correctly escaped
        self.assertNotIn("Create Purchase", html)
        # Fields self-style: label + control carry their own classes (no #add-form
        # / form CSS in input.css).
        self.assertIn("mb-2.5 text-type-label text-heading", html)  # _LABEL_CLASS
        self.assertIn("bg-neutral-secondary-medium", html)  # INPUT_CLASS surface
        self.assertNoEscapedTags(html)

    def test_form_errors_render_with_component_class(self):
        """Invalid submits re-render field errors via FormFields' own class, not
        Django's .errorlist (which no longer exists in the CSS)."""
        # Non-empty but invalid (name is required) so the form binds and
        # re-renders with errors — an empty {} POST is falsy and stays unbound.
        response = self.client.post(reverse("games:add_game"), {"status": "unplayed"})
        html = response.content.decode()
        # The class itself: a token the page shell carries elsewhere would
        # pass with no field error drawn at all.
        self.assertIn(_FIELD_ERROR_CLASS, html)
        self.assertNotIn('class="errorlist"', html)
        self.assertNoEscapedTags(html)

    def _element_with_id(self, html, element_id):
        """Return the single tag (e.g. an <input>) carrying ``id="<element_id>"``."""
        match = re.search(rf'<[^>]*\bid="{re.escape(element_id)}"[^>]*>', html)
        if match is None:
            self.fail(f"no element with id {element_id!r} in output")
        return match.group(0)

    def test_add_session_for_game_autofocuses_device_not_game(self):
        html = self.get("games:add_session_for_game", self.game.id).content.decode()
        self.assertIn("autofocus", self._element_with_id(html, "id_device"))
        self.assertNotIn("autofocus", self._element_with_id(html, "id_game"))

    def test_cold_add_forms_keep_game_autofocus(self):
        """Opened cold, the Game field keeps focus."""
        session_html = self.get("games:add_session").content.decode()
        self.assertIn("autofocus", self._element_with_id(session_html, "id_game"))
        self.assertNotIn("autofocus", self._element_with_id(session_html, "id_device"))

    def test_add_session_form_has_segmented_timestamp_fields(self):
        html = self.get("games:add_session").content.decode()
        for marker in [
            'field-name="started_at"',
            # The group takes its name from the row label rather than repeating
            # the string, so the label is not announced as its own object.
            'id="id_started_at-label"',
            'aria-labelledby="id_started_at-label"',
            'field-name="ended_at"',
            'data-date-time-hidden=""',
            'data-date-part="hour"',
            'data-date-part="minute"',
            # The helpers the old <session-timestamp-buttons> row carried, now
            # inside the widget: Now is a calendar footer button, copy is an
            # arrow addressing the other field.
            "Now",
            'data-date-time-copy="ended_at"',
            'data-date-time-copy="started_at"',
            "Copy start value to end",
            "Copy end value to start",
        ]:
            self.assertIn(marker, html)
        self.assertNoEscapedTags(html)

    # --- detail pages --------------------------------------------------------

    def test_view_game(self):
        html = self.client.get(self.game.get_absolute_url()).content.decode()
        for marker in [
            'id="game-info"',
            "text-type-title font-serif",
            self.game.name,
            "Total hours played",  # stat popover tooltip
            'id="popover-hours"',
            "Original release",
            "Status",
            "Played",
            "Platform",
            "Released",
            'id="history-container"',
            'event="status-changed"',
            'id="library"',
            "Add to library",
            "Sessions",
            "Playthroughs",
            "History",
        ]:
            self.assertIn(marker, html)
        self.assertNoEscapedTags(html)
        self.assertEqual(html.count("<div"), html.count("</div>"))

    def test_view_game_states_the_interface_figure(self):
        removed = session_row(
            self.game,
            started_at=datetime(2022, 9, 27, 15, 0, tzinfo=ZONEINFO),
            ended_at=datetime(2022, 9, 27, 17, 0, tzinfo=ZONEINFO),
        )
        #: A bare stamp; no stored total recounts.
        PlayerSession.objects.filter(pk=removed.pk).update(removed_at=timezone.now())

        html = self.client.get(self.game.get_absolute_url()).content.decode()
        hours = html[
            html.index('id="popover-hours"') : html.index('id="popover-sessions"')
        ]

        self.assertEqual(
            game_playtime(self.user.library, self.game).total, timedelta(hours=1)
        )
        self.assertIn("1 h 00 m", hours)
        self.assertNotIn("3 h 00 m", hours)

    def test_view_game_drops_the_flattened_release_year(self):
        """The title said a year no Release had to agree with."""
        Game.objects.filter(pk=self.game.pk).update(year_released=1999)

        html = self.client.get(self.game.get_absolute_url()).content.decode()

        self.assertNotIn('id="popover-year"', html)
        self.assertNotIn("Release year", html)

    def test_view_game_reads_the_original_release_date(self):
        self.game.original_release_date = TemporalValue.from_month(1984, 6)
        self.game.save()

        html = self.client.get(self.game.get_absolute_url()).content.decode()

        self.assertIn("Original release", html)
        self.assertIn("June 1984", html)
        self.assertNotIn("1984-06", html)

    def test_view_game_says_unknown_for_no_original_release_date(self):
        html = self.client.get(self.game.get_absolute_url()).content.decode()

        self.assertIn('<span class="text-heading">Unknown</span>', html)

    def test_played_row_count_link_is_a_single_anchor(self):
        """The 'N times' count control is one styled <a> (ControlButton href
        mode), not a <button> nested inside an <a> (invalid HTML)."""
        game = Game.objects.create(
            library=self.user.library, name="Anchor Game", platform=self.platform
        )
        html = self.client.get(game.get_absolute_url()).content.decode()
        count_at = html.index("data-count")
        control = html[html.rindex("<a", 0, count_at) : html.index("</a>", count_at)]
        self.assertNotIn("<button", control)
        # the anchor itself carries the outline-toggle look and its shape class
        self.assertIn("border-default-medium", control)
        self.assertIn("rounded-s-base", control)

    def test_played_row_label_is_one_flex_item(self):
        """'N times' is one prose phrase, so it must be a single flex item:
        the count anchor is inline-flex, and flex layout drops whitespace-only
        text between items — sibling span + " times" rendered as "0times"."""
        game = Game.objects.create(
            library=self.user.library, name="Prose Game", platform=self.platform
        )
        html = self.client.get(game.get_absolute_url()).content.decode()
        self.assertIn('<span><span data-count="">0</span> times</span>', html)

    def test_view_game_null_platform_and_null_device_fallbacks(self):
        """The two view-level fallback expressions on the game detail page:
        the Platform meta row shows "Unspecified" for a platformless game, and
        the sessions table shows "No device" for a device-less session."""
        platformless = Game.objects.create(
            library=self.user.library, name="Platformless Game"
        )
        session_row(
            platformless,
            started_at=datetime(2022, 9, 26, 15, 0, tzinfo=ZONEINFO),
            ended_at=datetime(2022, 9, 26, 16, 0, tzinfo=ZONEINFO),
        )
        html = self.client.get(platformless.get_absolute_url()).content.decode()
        self.assertIn("Unspecified", html)
        self.assertIn("No device", html)
        self.assertNoEscapedTags(html)

    def test_view_game_empty_sections(self):
        """A game with no sessions or purchases shows the empty messages."""
        lonely = Game.objects.create(
            library=self.user.library, name="Lonely Game", platform=self.platform
        )
        html = self.client.get(lonely.get_absolute_url()).content.decode()
        for marker in [
            "Nothing in your library yet.",
            "No sessions yet.",
        ]:
            self.assertIn(marker, html)
        self.assertNotIn("No playthroughs yet.", html)
        self.assertNoEscapedTags(html)

    # --- confirmation pages --------------------------------------------------

    def test_remove_game_confirmation_page(self):
        html = self.get("games:remove_game", self.game.id).content.decode()
        self.assertIn(self.game.name, html)
        self.assertIn("session(s)", html)  # seeded session
        self.assertIn("purchase(s)", html)  # seeded purchase
        self.assertIn('method="post"', html)
        self.assertNoEscapedTags(html)

    def test_session_list_actions_do_not_reach_the_api(self):
        # Finish and reset are ordinary POST routes that reload the page. The
        # device selector still PATCHes /api/session/<id>/device — that is a
        # different control and unaffected.
        html = self.get("games:list_sessions").content.decode()
        self.assertNotIn("<session-actions", html)
        self.assertNotIn(f'"/api/session/{self.session.id}"', html)
        self.assertNoEscapedTags(html)

    def test_finish_reset_buttons_only_shown_for_running_sessions(self):
        running = timed_row(
            tracked_run(self.user.library, self.game),
            datetime(2020, 1, 1, 10, 0, tzinfo=ZONEINFO),
            None,
        )
        html = self.get("games:list_sessions").content.decode()
        self.assertIn(f"/session/{running.id}/finish", html)
        self.assertIn(f"/session/{running.id}/reset", html)
        self.assertNotIn(f"/session/{self.session.id}/finish", html)
        self.assertNotIn(f"/session/{self.session.id}/reset", html)

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
        # text-type-input owns the flat 16px size token (stops iOS Safari
        # auto-zoom on focus, #427) — no responsive pair needed.
        self.assertRegex(html, r'name="username"[^>]*class="[^"]*\btext-type-input\b')

    # --- stats ---------------------------------------------------------------

    def test_stats_alltime(self):
        html = self.get("games:stats_alltime").content.decode()
        for marker in [
            "<drop-down",
            'data-year-picker-grid=""',
            'data-year-picker-template="year"',
            'aria-expanded="false"',
            "All-time stats",
            "Playtime",
            "Purchases",
            "Games by playtime",
            "Platforms by playtime",
        ]:
            self.assertIn(marker, html)
        # Stats tables are StyledTables now: the ranked (Games/Platforms) tables
        # render a tokenized <thead>. Anchored on the header row rather than any
        # <tr>: a body row's hover:bg-neutral-tertiary-medium would otherwise
        # false-match.
        self.assertRegex(html, r"<thead[^>]*>\s*<tr[^>]*bg-neutral-tertiary")
        self.assertNoEscapedTags(html)
        self.assertEqual(html.count("<table"), html.count("</table>"))

    def test_stats_by_year(self):
        year = self.session.started_at.year
        html = self.get("games:stats_by_year", year).content.decode()
        # The seeded game/session/purchase should surface in the year view.
        self.assertIn("Playtime per month", html)
        self.assertIn(self.game.name, html)
        self.assertNoEscapedTags(html)
        self.assertEqual(html.count("<table"), html.count("</table>"))

    def test_stats_table_uses_type_tokens(self):
        html = self.get("games:stats_alltime").content.decode()
        # StyledTable carries the type tokens on the container elements, not the
        # cells: text-type-micro on <thead>, text-type-body on <table>.
        self.assertRegex(html, r"<thead[^>]*\btext-type-micro\b")
        self.assertRegex(html, r"<table[^>]*\btext-type-body\b")


class PurchaseListDateFilterTest(TestCase):
    """End-to-end: GET /tracker/purchase/list?filter=… narrows the rendered
    list and pre-fills the date inputs from the URL filter.

    Replaces the manual curl smoke that earlier verified the same path.
    """

    def setUp(self) -> None:

        self.user = User.objects.create_superuser(
            username="datetester", email="dt@example.com", password="testpass"
        )
        self.client.force_login(self.user)
        self.platform = Platform.objects.create(
            library=self.user.library, name="DateP", icon="gog"
        )
        # Markers are the game names the Name column prints.
        bought = []
        for name, purchased in (
            ("EARLY-MARKER", "2024-01-15"),
            ("MID-MARKER", "2024-06-15"),
            ("LATE-MARKER", "2025-01-15"),
        ):
            game = Game(library=self.user.library, name=name, platform=self.platform)
            graph = default_graph(game, self.user.library, platform=self.platform)
            bought.append(
                record_purchase(
                    record_entry(self.user.library, graph.release),
                    kind="season_pass",
                    name="Pass",
                    purchased=TemporalValue.parse(purchased),
                )
            )
        self.early, self.mid, self.late = bought
        refund_purchase(self.mid, TemporalValue.parse("2024-07-01"))

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
        # The visual-only tooltip repeats the full string in an aria-hidden
        # panel; count the actual table-cell clip, not all text nodes.
        for marker in ("EARLY-MARKER", "MID-MARKER", "LATE-MARKER"):
            self.assertEqual(
                len(
                    re.findall(
                        rf'data-truncated-clip=""[^>]*>Pass · {re.escape(marker)}',
                        html,
                    )
                ),
                1,
            )

    def test_purchased_between_narrows_and_prepopulates(self):
        """BETWEEN 2024-01-01..2024-12-31 → only early + mid; both date
        inputs pre-filled with the filter bounds."""
        response = self._get(
            {
                "purchased": {
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
            'name="quick-purchased-min" id="quick-purchased-min" value="2024-01-01"',
            html,
        )
        self.assertIn(
            'name="quick-purchased-max" id="quick-purchased-max" value="2024-12-31"',
            html,
        )

    def test_purchased_greater_than_single_bound(self):
        """GREATER_THAN populates min only, leaves max blank."""
        response = self._get(
            {
                "purchased": {
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
            'name="quick-purchased-min" id="quick-purchased-min" value="2024-06-15"',
            html,
        )
        self.assertIn(
            'name="quick-purchased-max" id="quick-purchased-max" value=""',
            html,
        )

    def test_refunded_not_null(self):
        response = self._get({"refunded": {"value": "", "modifier": "NOT_NULL"}})
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertNotIn("EARLY-MARKER", html)
        self.assertIn("MID-MARKER", html)
        self.assertNotIn("LATE-MARKER", html)

    def test_combined_dates_and_is_refunded(self):
        """purchased BETWEEN 2024 AND refunded NOT_NULL → only the
        mid purchase. Confirms AND-composition through the view layer."""
        response = self._get(
            {
                "purchased": {
                    "value": "2024-01-01",
                    "value2": "2024-12-31",
                    "modifier": "BETWEEN",
                },
                "refunded": {"value": "", "modifier": "NOT_NULL"},
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

    def test_a_legacy_key_warns_and_falls_back(self):
        """A filter the legacy list spelled is refused, not dropped."""
        response = self._get(
            {"date_purchased": {"value": "2024-06-15", "modifier": "GREATER_THAN"}}
        )
        html = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertIn("EARLY-MARKER", html)
        self.assertIn("Ignored invalid filter", html)

    def test_semantically_invalid_filter_warns_and_falls_back(self):
        """Parseable JSON but a build-time-invalid filter (BETWEEN without value2)
        must warn-and-ignore, not 500."""
        response = self._get(
            {"purchased": {"value": "2024-01-01", "modifier": "BETWEEN"}}
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
        self.platform = Platform.objects.create(
            library=self.user.library, name="GFP", icon="egs"
        )
        self.played = Game.objects.create(
            library=self.user.library, name="PLAYED-MARKER", platform=self.platform
        )
        self.unplayed = Game.objects.create(
            library=self.user.library, name="UNPLAYED-MARKER", platform=self.platform
        )
        start = timezone.now()
        session_row(
            self.played,
            started_at=start,
            ended_at=start + timedelta(hours=2),
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
                        "duration_hours": {"modifier": "BETWEEN", "value": 1}
                    }
                }
            )
        )
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("PLAYED-MARKER", html)
        self.assertIn("UNPLAYED-MARKER", html)
        self.assertIn("Ignored invalid filter", html)


@pytest.mark.django_db(transaction=True)
def test_add_game_submit_and_add_to_library_redirects(
    client, owned_user, catalog_graph_post
):
    #: Out of the TestCase, because the POST dispatches.
    #: A transactional class truncates for all to serve one.
    client.force_login(owned_user)

    response = client.post(
        reverse("games:add_game"),
        {
            "name": "New Session Game",
            "status": "unplayed",
            "submit_and_add_to_library": "",
            **catalog_graph_post(),
        },
    )

    game = Game.objects.get(name="New Session Game")
    assertRedirects(
        response,
        reverse("games:add_library_entry", kwargs={"game_id": game.id}),
    )


@pytest.mark.django_db
def test_the_navbar_week_counts_six_days_back_and_not_seven(owned_user):
    from django.test import RequestFactory

    from games.views.general import model_counts

    game = Game.objects.create(library=owned_user.library, name="Tunic")
    for days_back, hours in ((6, 1), (7, 2)):
        start = library_noon(owned_user.library, days_ago=days_back)
        session_row(
            game,
            started_at=start,
            ended_at=start + timedelta(hours=hours),
        )
    request = RequestFactory().get("/")
    request.user = owned_user

    last_seven_days = str(model_counts(request)["last_7_played"])

    assert "1 h 00 m" in last_seven_days
    assert "3 h 00 m" not in last_seven_days
