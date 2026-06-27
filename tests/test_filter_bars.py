"""Characterization tests locking the rendered output of the three filter bars.

The FilterBar family (FilterBar / SessionFilterBar / PurchaseFilterBar) pins the
structural contract — form/input ids, the hidden ``filter`` field, preset wiring,
the filter_json round-trip, no double-escaping, and the Stash-style NumberFilter /
StringFilter modifier widgets — so refactors stay behaviour-preserving.
"""

import json

from django.test import TestCase

from common.components import (
    FilterBar,
    NumberFilter,
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

    def _assert_number_filter(self, html, field_prefix):
        """Every filter bar must use the Stash-style NumberFilter: a modifier
        radio grid plus two number inputs (value + value2), with no legacy
        RangeSlider custom element left behind."""
        self.assertIn("data-number-modifier-radio", html)
        self.assertIn(f'name="{field_prefix}-modifier"', html)
        self.assertIn('value="BETWEEN"', html)
        self.assertIn('value="IS_NULL"', html)
        self.assertIn(f'name="{field_prefix}"', html)
        self.assertIn(f'name="{field_prefix}-value2"', html)
        self.assertIn("data-number-value2", html)
        # The old slider element must be fully gone.
        self.assertNotIn("<range-slider", html)
        self.assertNotIn("range-mode-toggle", html)

    def test_game_filter_bar(self):
        html = str(
            FilterBar(
                filter_json="",
                preset_list_url="/presets/games/list",
                preset_save_url="/presets/games/save",
            )
        )
        self._assert_shell(html, "/presets/games/list", "/presets/games/save")
        self._assert_number_filter(html, "filter-year")

    def test_session_filter_bar(self):
        html = str(
            SessionFilterBar(
                filter_json="",
                preset_list_url="/presets/sessions/list",
                preset_save_url="/presets/sessions/save",
            )
        )
        self._assert_shell(html, "/presets/sessions/list", "/presets/sessions/save")
        self._assert_number_filter(html, "filter-duration-total-hours")

    def test_purchase_filter_bar(self):
        html = str(
            PurchaseFilterBar(
                filter_json="",
                preset_list_url="/presets/purchases/list",
                preset_save_url="/presets/purchases/save",
            )
        )
        self._assert_shell(html, "/presets/purchases/list", "/presets/purchases/save")
        self._assert_number_filter(html, "filter-price")

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
        games_start = html.find('name="games"')
        platform_start = html.find('name="platform"')
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
        self.assertIn('filter-mode="true"', html)
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

    def test_playevent_filter_bar_renders_date_inputs(self):
        """PlayEventFilterBar surfaces started and ended as DateRangePicker
        widgets whose -min/-max hidden inputs (the JS serializer contract)
        carry the filter-started / filter-ended prefixes, in labelled fields."""
        from common.components import PlayEventFilterBar

        html = str(
            PlayEventFilterBar(
                filter_json="", preset_list_url="/l", preset_save_url="/s"
            )
        )
        for name in (
            "filter-started-min",
            "filter-started-max",
            "filter-ended-min",
            "filter-ended-max",
        ):
            self.assertIn(f'name="{name}"', html)
            self.assertIn(f'id="{name}"', html)
        self.assertIn("<date-range-picker", html)
        self.assertIn("Started", html)
        self.assertIn("Finished", html)
        self.assertNoEscapedTags(html)

    def test_playevent_filter_bar_prepopulates_ended_between(self):
        """A BETWEEN filter on ended populates both date bounds via _parse_range."""
        from common.components import PlayEventFilterBar

        filter_json = json.dumps(
            {
                "ended": {
                    "value": "2024-01-01",
                    "value2": "2024-12-31",
                    "modifier": "BETWEEN",
                }
            }
        )
        html = str(
            PlayEventFilterBar(
                filter_json=filter_json,
                preset_list_url="/l",
                preset_save_url="/s",
            )
        )
        self.assertIn(
            'name="filter-ended-min" id="filter-ended-min" value="2024-01-01"',
            html,
        )
        self.assertIn(
            'name="filter-ended-max" id="filter-ended-max" value="2024-12-31"',
            html,
        )

    def test_playevent_filter_bar_labels_days_to_finish_slider(self):
        """The Days to Finish NumberFilter must be wrapped in a labelled field —
        NumberFilter does not render its own label, so a bare widget shows none."""
        from common.components import PlayEventFilterBar

        html = str(
            PlayEventFilterBar(
                filter_json="", preset_list_url="/l", preset_save_url="/s"
            )
        )
        self.assertIn("Days to Finish", html)
        self.assertNoEscapedTags(html)

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
        self.assertIn('search-url="/api/devices/search"', html)
        self.assertIn('search-url="/api/platforms/groups"', html)
        # New enum selects (purchase type / ownership)
        self.assertIn('name="purchase_type"', html)
        self.assertIn('name="purchase_ownership_type"', html)
        # Free-text widget for playevent notes (now StringFilter)
        self.assertIn('name="filter-playevent_note"', html)
        self.assertIn('name="filter-playevent_note-modifier"', html)
        # New NumberFilter input prefixes (value input named by bare prefix)
        self.assertIn('name="filter-purchase-count"', html)
        self.assertIn('name="filter-purchase-count-value2"', html)
        self.assertIn('name="filter-playevent-count"', html)
        self.assertIn('name="filter-manual-playtime-hours"', html)
        self.assertIn('name="filter-calculated-playtime-hours"', html)
        self.assertIn('name="filter-original-year"', html)
        self.assertIn('name="filter-purchase-price-total"', html)
        self.assertIn('name="filter-purchase-price-any"', html)
        self.assertIn('name="filter-purchase-count-modifier"', html)
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

    def test_purchase_filter_bar_renders_finished_dates(self):
        """PurchaseFilterBar exposes the #121 'Finished' date-range widget."""
        html = str(
            PurchaseFilterBar(
                filter_json="", preset_list_url="/l", preset_save_url="/s"
            )
        )
        self.assertIn('name="filter-finished-min"', html)
        self.assertIn('name="filter-finished-max"', html)

    def test_game_filter_bar_renders_finished_dates(self):
        """The Game filter bar exposes the #121 'Finished' date-range widget."""
        from common.components import FilterBar

        html = str(FilterBar(filter_json=""))
        self.assertIn('name="filter-finished-min"', html)
        self.assertIn('name="filter-finished-max"', html)

    def test_finished_filter_prepopulates_less_than_into_max(self):
        """A LESS_THAN (max-only) finished filter fills the max slot, not min —
        guards the modifier-aware _parse_range fix."""
        filter_json = json.dumps(
            {"finished": {"value": "2024-12-31", "modifier": "LESS_THAN"}}
        )
        html = str(
            PurchaseFilterBar(
                filter_json=filter_json,
                preset_list_url="/l",
                preset_save_url="/s",
            )
        )
        self.assertIn(
            'name="filter-finished-min" id="filter-finished-min" value=""', html
        )
        self.assertIn(
            'name="filter-finished-max" id="filter-finished-max" value="2024-12-31"',
            html,
        )

    def test_finished_filter_prepopulates_greater_than_into_min(self):
        """A GREATER_THAN (min-only) finished filter fills the min slot — the
        symmetric counterpart to the LESS_THAN case above."""
        filter_json = json.dumps(
            {"finished": {"value": "2024-01-01", "modifier": "GREATER_THAN"}}
        )
        html = str(
            PurchaseFilterBar(
                filter_json=filter_json,
                preset_list_url="/l",
                preset_save_url="/s",
            )
        )
        self.assertIn(
            'name="filter-finished-min" id="filter-finished-min" value="2024-01-01"',
            html,
        )
        self.assertIn(
            'name="filter-finished-max" id="filter-finished-max" value=""', html
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


class NumberFilterRenderTest(TestCase):
    """Render-level contract for the Stash-style NumberFilter component."""

    def test_renders_all_eight_modifier_radios(self):
        html = str(
            NumberFilter(input_name_prefix="filter-year", path=["year_released"])
        )
        for modifier in (
            "EQUALS",
            "NOT_EQUALS",
            "GREATER_THAN",
            "LESS_THAN",
            "BETWEEN",
            "NOT_BETWEEN",
            "IS_NULL",
            "NOT_NULL",
        ):
            self.assertIn(f'value="{modifier}"', html)
        self.assertIn("data-number-modifier-radio", html)

    def test_renders_two_number_inputs(self):
        html = str(
            NumberFilter(input_name_prefix="filter-year", path=["year_released"])
        )
        self.assertIn('type="number"', html)
        self.assertIn('name="filter-year"', html)
        self.assertIn('name="filter-year-value2"', html)
        self.assertIn("data-number-value2", html)

    def test_default_modifier_hides_second_input_and_enables_inputs(self):
        html = str(
            NumberFilter(input_name_prefix="filter-year", path=["year_released"])
        )
        # value2 is hidden for the default EQUALS modifier.
        self.assertRegex(html, r'data-number-value2="" class="[^"]*\bhidden\b')
        # Inputs are not disabled by default.
        self.assertNotIn("disabled", html)

    def test_between_shows_second_input_and_prefills_values(self):
        html = str(
            NumberFilter(
                input_name_prefix="filter-year",
                value="2000",
                value2="2010",
                modifier="BETWEEN",
                path=["year_released"],
            )
        )
        self.assertIn('value="2000"', html)
        self.assertIn('value="2010"', html)
        # The second input must NOT carry the hidden class under BETWEEN.
        self.assertNotRegex(html, r'data-number-value2="" class="[^"]*\bhidden\b')

    def test_presence_modifier_disables_and_clears_inputs(self):
        html = str(
            NumberFilter(
                input_name_prefix="filter-year",
                value="2000",
                value2="2010",
                modifier="IS_NULL",
                path=["year_released"],
            )
        )
        self.assertIn("disabled", html)
        self.assertIn("cursor-not-allowed", html)
        # Values are cleared while disabled.
        self.assertNotIn('value="2000"', html)
        self.assertNotIn('value="2010"', html)

    def test_invalid_modifier_falls_back_to_equals(self):
        html = str(
            NumberFilter(
                input_name_prefix="filter-year",
                modifier="INCLUDES",
                path=["year_released"],
            )
        )
        # EQUALS is the only checked radio when an invalid modifier is given.
        self.assertRegex(html, r'value="EQUALS"[^>]*checked="true"')
        self.assertNotRegex(html, r'value="INCLUDES"')
