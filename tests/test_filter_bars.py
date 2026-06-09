"""Characterization tests locking the rendered output of the three filter bars.

The FilterBar family (FilterBar / SessionFilterBar / PurchaseFilterBar) is the
target of a dedup + module split + RangeSlider component extraction. These tests
pin the structural contract — form/input ids, the hidden ``filter`` field,
preset wiring, the filter_json round-trip, no double-escaping, and the
Flowbite-styled native range slider unification — so that refactor stays
behaviour-preserving.
"""

import json

from django.test import TestCase

from common.components import (
    FilterBar,
    PurchaseFilterBar,
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

    def _assert_range_slider(self, html):
        """Every filter bar must use the RangeSlider component with custom
        draggable <div> handles, a track fill, and mode-toggle button."""
        self.assertIn("range-slider-block", html)
        self.assertIn('data-mode="range"', html)
        self.assertIn("range-mode-toggle", html)
        self.assertIn("range-mode-icon-range", html)
        self.assertIn("range-mode-icon-point", html)
        self.assertIn("range-track-fill", html)
        self.assertIn("range-handle-min", html)
        self.assertIn("range-handle-max", html)
        # No native range inputs
        self.assertNotIn(
            '<input type="range"',
            html,
            "native <input type=range> found — should use custom div handles",
        )

    def test_game_filter_bar(self):
        html = str(
            FilterBar(
                filter_json="",
                preset_list_url="/presets/games/list",
                preset_save_url="/presets/games/save",
            )
        )
        self._assert_shell(html, "/presets/games/list", "/presets/games/save")
        self._assert_range_slider(html)

    def test_session_filter_bar(self):
        html = str(
            SessionFilterBar(
                filter_json="",
                preset_list_url="/presets/sessions/list",
                preset_save_url="/presets/sessions/save",
            )
        )
        self._assert_shell(html, "/presets/sessions/list", "/presets/sessions/save")
        self._assert_range_slider(html)

    def test_purchase_filter_bar(self):
        html = str(
            PurchaseFilterBar(
                filter_json="",
                preset_list_url="/presets/purchases/list",
                preset_save_url="/presets/purchases/save",
            )
        )
        self._assert_shell(html, "/presets/purchases/list", "/presets/purchases/save")
        self._assert_range_slider(html)

    def test_purchase_filter_bar_games_has_m2m_modifiers(self):
        """The many-to-many games field surfaces (All)/(Only) pseudo-options
        in the dropdown alongside the presence (Any)/(None) rows. Single-valued
        fields (platform) do not get M2M modifiers."""
        html = str(
            PurchaseFilterBar(
                filter_json="", preset_list_url="/l", preset_save_url="/s"
            )
        )
        # (All) and (Only) appear as modifier rows in the dropdown.
        self.assertIn('data-search-select-modifier-option="INCLUDES_ALL"', html)
        self.assertIn('data-search-select-modifier-option="INCLUDES_ONLY"', html)
        # No legacy match-mode <select>.
        self.assertNotIn("data-search-select-match", html)
        # Platform is single-valued: no M2M modifier options in its section.
        games_start = html.find('data-name="games"')
        platform_start = html.find('data-name="platform"')
        platform_section = html[platform_start:]
        self.assertNotIn("INCLUDES_ALL", platform_section)
        self.assertGreater(games_start, 0)

    def test_purchase_filter_bar_roundtrips_includes_all(self):
        """A stored INCLUDES_ALL modifier renders as the modifier pill and the
        included game still renders as a value pill."""
        filter_json = json.dumps(
            {
                "games": {
                    "value": [{"id": "5", "label": "Hollow Knight"}],
                    "modifier": "INCLUDES_ALL",
                }
            }
        )
        html = str(
            PurchaseFilterBar(
                filter_json=filter_json, preset_list_url="/l", preset_save_url="/s"
            )
        )
        self.assertIn('data-modifier="INCLUDES_ALL"', html)
        self.assertIn("(All)", html)  # modifier pill label
        self.assertIn("Hollow Knight", html)
        self.assertIn('data-search-select-type="include"', html)
        self.assertNoEscapedTags(html)

    def test_game_filter_bar_roundtrips_selected_status(self):
        """A status in filter_json renders as an include pill in the widget."""
        filter_json = json.dumps(
            {
                "status": {
                    "value": [{"id": "f", "label": "Finished"}],
                    "modifier": "INCLUDES",
                }
            }
        )
        html = str(
            FilterBar(
                filter_json=filter_json, preset_list_url="/l", preset_save_url="/s"
            )
        )
        self.assertIn('data-search-select-mode="filter"', html)
        self.assertIn(
            'data-search-select-type="include"', html
        )  # rendered as an include pill
        self.assertIn('data-value="f"', html)  # selected status reflected in widget
        self.assertIn("Finished", html)  # ...with its label
        self.assertNoEscapedTags(html)
        # The hidden #filter-json-input must be escaped exactly once, so the DOM
        # value is valid JSON the apply/preset JS can re-parse. Regression guard
        # for the double-escape bug the dedup fixed.
        self.assertIn("&quot;status&quot;", html)
        self.assertNotIn("&amp;quot;", html)

    def test_game_filter_bar_preserves_excludes_modifier(self):
        """An enum field with an EXCLUDES modifier renders data-modifier correctly
        so the JS roundtrip preserves the modifier (regression: _split_modifier
        silently dropped non-presence modifiers when match_modes was None)."""
        filter_json = json.dumps(
            {
                "status": {
                    "value": [{"id": "f", "label": "Finished"}],
                    "modifier": "EXCLUDES",
                }
            }
        )
        html = str(
            FilterBar(
                filter_json=filter_json, preset_list_url="/l", preset_save_url="/s"
            )
        )
        # The full modifier is stored on data-modifier when there's no match-mode
        # select (enum/choice fields).  No data-match attribute is present.
        self.assertIn('data-modifier="EXCLUDES"', html)
        self.assertNotIn("data-match=", html)
        self.assertIn("Finished", html)
        self.assertNoEscapedTags(html)
