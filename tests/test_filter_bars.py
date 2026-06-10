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

    def test_device_filter_bar(self):
        from common.components import DeviceFilterBar

        html = str(
            DeviceFilterBar(
                filter_json="",
                preset_list_url="/presets/devices/list",
                preset_save_url="/presets/devices/save",
            )
        )
        self._assert_shell(html, "/presets/devices/list", "/presets/devices/save")

    def test_platform_filter_bar(self):
        from common.components import PlatformFilterBar

        html = str(
            PlatformFilterBar(
                filter_json="",
                preset_list_url="/presets/platforms/list",
                preset_save_url="/presets/platforms/save",
            )
        )
        self._assert_shell(html, "/presets/platforms/list", "/presets/platforms/save")

    def test_playevent_filter_bar(self):
        from common.components import PlayEventFilterBar

        html = str(
            PlayEventFilterBar(
                filter_json="",
                preset_list_url="/presets/playevents/list",
                preset_save_url="/presets/playevents/save",
            )
        )
        self._assert_shell(html, "/presets/playevents/list", "/presets/playevents/save")

    def test_game_filter_bar_has_new_widgets(self):
        """The expanded games FilterBar exposes platform_group, device, playevent_note,
        purchase_type / purchase_ownership_type, plus count and aggregate-playtime
        range sliders and the new boolean checkboxes."""
        html = str(
            FilterBar(
                filter_json="",
                preset_list_url="/l",
                preset_save_url="/s",
            )
        )
        # New search-backed selects
        self.assertIn('data-search-url="/api/devices/search"', html)
        self.assertIn('data-search-url="/api/platforms/groups"', html)
        # New enum selects (purchase type / ownership)
        self.assertIn('data-name="purchase_type"', html)
        self.assertIn('data-name="purchase_ownership_type"', html)
        # Free-text widget for playevent notes (now StringFilter)
        self.assertIn('name="filter-playevent_note"', html)
        self.assertIn('name="filter-playevent_note-modifier"', html)
        # New range slider input prefixes
        self.assertIn('name="filter-purchase-count-min"', html)
        self.assertIn('name="filter-playevent-count-min"', html)
        self.assertIn('name="filter-manual-playtime-minutes-min"', html)
        self.assertIn('name="filter-calculated-playtime-minutes-min"', html)
        self.assertIn('name="filter-original-year-min"', html)
        self.assertIn('name="filter-purchase-price-total-min"', html)
        self.assertIn('name="filter-purchase-price-any-min"', html)
        # New boolean checkboxes
        self.assertIn('name="filter-purchase-refunded"', html)
        self.assertIn('name="filter-purchase-infinite"', html)
        self.assertIn('name="filter-session-emulated"', html)
        # Removed boolean checkboxes
        self.assertNotIn('name="filter-has-purchases"', html)
        self.assertNotIn('name="filter-has-playevents"', html)
        # Playtime label renamed
        self.assertIn("Total playtime", html)

    def test_purchase_filter_bar_renders_date_inputs(self):
        """PurchaseFilterBar surfaces date_purchased and date_refunded as
        type=date input pairs with -min/-max naming."""
        html = str(
            PurchaseFilterBar(
                filter_json="", preset_list_url="/l", preset_save_url="/s"
            )
        )
        for name in (
            "filter-date-purchased-min",
            "filter-date-purchased-max",
            "filter-date-refunded-min",
            "filter-date-refunded-max",
        ):
            self.assertIn(f'name="{name}"', html)
            self.assertIn(f'id="{name}"', html)
        # Inputs are native date pickers, not text.
        self.assertIn('type="date"', html)
        self.assertNoEscapedTags(html)

    def test_purchase_filter_bar_prepopulates_dates_between(self):
        """A BETWEEN filter populates both date bounds via _parse_range."""
        filter_json = json.dumps(
            {
                "date_purchased": {
                    "value": "2024-01-01",
                    "value2": "2024-12-31",
                    "modifier": "BETWEEN",
                }
            }
        )
        html = str(
            PurchaseFilterBar(
                filter_json=filter_json,
                preset_list_url="/l",
                preset_save_url="/s",
            )
        )
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

    def test_purchase_filter_bar_prepopulates_dates_single_bound(self):
        """A single-bound (GREATER_THAN) filter populates min only."""
        filter_json = json.dumps(
            {
                "date_refunded": {
                    "value": "2024-06-01",
                    "modifier": "GREATER_THAN",
                }
            }
        )
        html = str(
            PurchaseFilterBar(
                filter_json=filter_json,
                preset_list_url="/l",
                preset_save_url="/s",
            )
        )
        self.assertIn(
            'name="filter-date-refunded-min" id="filter-date-refunded-min" '
            'value="2024-06-01"',
            html,
        )
        # Max input is still present but with empty value.
        self.assertIn(
            'name="filter-date-refunded-max" id="filter-date-refunded-max" value=""',
            html,
        )

    def test_boolean_fields_render_as_radio_groups(self):
        """Boolean fields must render as radio groups with True/False choices."""
        from common.components import FilterBar, SessionFilterBar, PurchaseFilterBar

        # 1. Games Filter Bar
        games_html = str(FilterBar(filter_json=""))
        self.assertIn('type="radio"', games_html)
        self.assertIn('name="filter-mastered"', games_html)
        self.assertIn('value="true"', games_html)
        self.assertIn('value="false"', games_html)

        # 2. Session Filter Bar
        session_html = str(SessionFilterBar(filter_json=""))
        self.assertIn('type="radio"', session_html)
        self.assertIn('name="filter-emulated"', session_html)
        self.assertIn('value="true"', session_html)
        self.assertIn('value="false"', session_html)

        # 3. Purchase Filter Bar
        purchase_html = str(PurchaseFilterBar(filter_json=""))
        self.assertIn('type="radio"', purchase_html)
        self.assertIn('name="filter-refunded"', purchase_html)
        self.assertIn('value="true"', purchase_html)
        self.assertIn('value="false"', purchase_html)

