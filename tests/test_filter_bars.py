"""Characterization tests locking the rendered output of the three filter bars.

The FilterBar family (FilterBar / SessionFilterBar / PurchaseFilterBar) is the
target of an upcoming dedup + module split. These tests pin the structural
contract — form/input ids, the hidden ``filter`` field, preset wiring, the
filter_json round-trip, and no double-escaping — so that refactor stays
behaviour-preserving. The renderers were previously untested.
"""

import json

from django.test import TestCase

from common.components import (
    FilterBar,
    PurchaseFilterBar,
    SelectableFilter,
    SessionFilterBar,
)
from games.models import Device, Game, Platform

_ESCAPED_TAG_MARKERS = ["&lt;div", "&lt;span", "&lt;button", "&lt;input", "&lt;a"]


class FilterBarRenderingTest(TestCase):
    def setUp(self):
        self.platform = Platform.objects.create(name="PC", icon="pc")
        self.device = Device.objects.create(name="Desktop")
        self.game = Game.objects.create(name="Test Game", platform=self.platform)

    def assertNoEscapedTags(self, html):
        for marker in _ESCAPED_TAG_MARKERS:
            self.assertNotIn(marker, html, f"double-escaped markup ({marker!r})")

    def _assert_shell(self, html, list_url, save_url):
        """Markers every filter bar must keep through the refactor."""
        self.assertIn('id="filter-bar-form"', html)
        self.assertIn('id="filter-json-input"', html)
        self.assertIn('name="filter"', html)
        self.assertIn(list_url, html)  # preset list URL wired in
        self.assertIn(save_url, html)  # preset save URL wired in
        self.assertNoEscapedTags(html)

    def test_game_filter_bar(self):
        html = str(
            FilterBar(
                filter_json="",
                preset_list_url="/presets/games/list",
                preset_save_url="/presets/games/save",
            )
        )
        self._assert_shell(html, "/presets/games/list", "/presets/games/save")

    def test_session_filter_bar(self):
        html = str(
            SessionFilterBar(
                filter_json="",
                preset_list_url="/presets/sessions/list",
                preset_save_url="/presets/sessions/save",
            )
        )
        self._assert_shell(html, "/presets/sessions/list", "/presets/sessions/save")

    def test_purchase_filter_bar(self):
        html = str(
            PurchaseFilterBar(
                filter_json="",
                preset_list_url="/presets/purchases/list",
                preset_save_url="/presets/purchases/save",
            )
        )
        self._assert_shell(html, "/presets/purchases/list", "/presets/purchases/save")

    def test_game_filter_bar_roundtrips_selected_status(self):
        """A status in filter_json renders as a selected tag in the widget."""
        filter_json = json.dumps({"status": {"value": ["f"], "modifier": ""}})
        html = str(
            FilterBar(
                filter_json=filter_json, preset_list_url="/l", preset_save_url="/s"
            )
        )
        self.assertIn("sf-tag", html)
        self.assertIn('data-value="f"', html)  # selected status reflected in widget
        self.assertIn("Finished", html)  # ...with its label
        self.assertNoEscapedTags(html)
        # The hidden #filter-json-input must be escaped exactly once, so the DOM
        # value is valid JSON the apply/preset JS can re-parse. Regression guard
        # for the double-escape bug the dedup fixed.
        self.assertIn("&quot;status&quot;", html)
        self.assertNotIn("&amp;quot;", html)


class SelectableFilterTest(TestCase):
    """The shared widget the deduped FilterBar will be built on."""

    OPTIONS = [("f", "Finished"), ("a", "Abandoned"), ("u", "Unplayed")]

    def test_plain_widget_has_no_tags(self):
        html = str(SelectableFilter("status", self.OPTIONS))
        self.assertNotIn("sf-tag", html)

    def test_include_and_exclude_tags(self):
        html = str(
            SelectableFilter("status", self.OPTIONS, selected=["f"], excluded=["a"])
        )
        self.assertIn('data-type="include"', html)
        self.assertIn('data-type="exclude"', html)
        self.assertIn("Finished", html)
        self.assertIn("Abandoned", html)
