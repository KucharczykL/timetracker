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


def _exclude_input_tag(html: str) -> str:
    """Extract the <input> tag for the free-text exclude checkbox."""
    marker = 'name="filter-search-exclude"'
    position = html.index(marker)
    start = html.rindex("<input", 0, position)
    end = html.index(">", position)
    return html[start : end + 1]


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
        <select> plus two number inputs (value + value2), with no legacy
        RangeSlider custom element left behind."""
        self.assertIn("data-number-modifier-select", html)
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
        so the JS roundtrip preserves the modifier (regression: non-presence
        modifiers were silently dropped when match_modes was None)."""
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
        <date-range-picker> widgets with -min/-max hidden-input naming."""
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
        # Both date filters now render via the canonical <date-range-picker> (#242
        # normalized Refunded off the bare native-date inputs).
        self.assertIn("<date-range-picker", html)
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
        guards the modifier-aware _range_from_field fix. The purchase `finished`
        widget is cross-entity (#123 Phase 2d), so it prefills from the nested AND
        sub-filter form (game_filter→playevent_filter→ended), not a flat key."""
        filter_json = json.dumps(
            {
                "AND": [
                    {
                        "game_filter": {
                            "playevent_filter": {
                                "ended": {
                                    "value": "2024-12-31",
                                    "modifier": "LESS_THAN",
                                }
                            }
                        }
                    }
                ]
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
            'name="filter-finished-min" id="filter-finished-min" value=""', html
        )
        self.assertIn(
            'name="filter-finished-max" id="filter-finished-max" value="2024-12-31"',
            html,
        )

    def test_finished_filter_prepopulates_greater_than_into_min(self):
        """A GREATER_THAN (min-only) finished filter fills the min slot — the
        symmetric counterpart to the LESS_THAN case above, in the nested AND
        cross-entity form."""
        filter_json = json.dumps(
            {
                "AND": [
                    {
                        "game_filter": {
                            "playevent_filter": {
                                "ended": {
                                    "value": "2024-01-01",
                                    "modifier": "GREATER_THAN",
                                }
                            }
                        }
                    }
                ]
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

    def test_filter_bar_renders_search_controls(self):
        """The free-text search input + exclude toggle are server-rendered."""
        html = str(
            FilterBar(
                preset_list_url="/presets/list",
                preset_save_url="/presets/save",
            )
        )
        self.assertIn('name="filter-search"', html)
        self.assertIn('name="filter-search-exclude"', html)
        self.assertIn("Exclude matches", html)
        # With no stored filter the exclude box must default to unchecked.
        self.assertNotIn("checked", _exclude_input_tag(html))
        self.assertNoEscapedTags(html)

    def test_search_controls_present_in_every_bar(self):
        """The search field is shared chrome rendered by _FilterBarBase, so all
        six bars carry both controls — guards against a render() override
        dropping it (mirrors FieldComparisonWidgetTest.test_widget_present_in_every_bar)."""
        from common.components import (
            DeviceFilterBar,
            FilterBar,
            PlatformFilterBar,
            PlayEventFilterBar,
            PurchaseFilterBar,
            SessionFilterBar,
        )

        bars = [
            FilterBar,
            SessionFilterBar,
            PurchaseFilterBar,
            DeviceFilterBar,
            PlatformFilterBar,
            PlayEventFilterBar,
        ]
        for bar in bars:
            html = str(bar(filter_json=""))
            self.assertIn('name="filter-search"', html, bar.__name__)
            self.assertIn('name="filter-search-exclude"', html, bar.__name__)

    def test_filter_bar_search_prefills_value_and_exclude(self):
        """A stored EXCLUDES search prefills the input value and checks the box."""
        filter_json = json.dumps(
            {"search": {"value": "Witcher", "modifier": "EXCLUDES"}}
        )
        html = str(FilterBar(filter_json=filter_json))
        self.assertIn('value="Witcher"', html)
        # The checkbox renders with a checked attribute (Checkbox uses checked="true").
        self.assertIn('name="filter-search-exclude"', html)
        self.assertIn("checked", _exclude_input_tag(html))

    def test_filter_bar_search_includes_leaves_box_unchecked(self):
        """An INCLUDES search prefills the value but does not check exclude."""
        filter_json = json.dumps(
            {"search": {"value": "Witcher", "modifier": "INCLUDES"}}
        )
        html = str(FilterBar(filter_json=filter_json))
        self.assertIn('value="Witcher"', html)
        # Isolate the exclude checkbox's own markup and assert it is unchecked.
        self.assertNotIn("checked", _exclude_input_tag(html))


class NumberFilterRenderTest(TestCase):
    """Render-level contract for the Stash-style NumberFilter component."""

    def test_renders_all_eight_modifier_options(self):
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
        self.assertIn("data-number-modifier-select", html)

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
        # Inputs are not disabled by default (the select's class carries the
        # `disabled:` utility variants, so match the real disabled attribute).
        self.assertNotIn('disabled="true"', html)

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
        self.assertIn('disabled="true"', html)
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
        # EQUALS is the selected option when an invalid modifier is given.
        self.assertRegex(html, r'value="EQUALS"[^>]*selected')
        self.assertNotRegex(html, r'value="INCLUDES"')


class FieldComparisonWidgetTest(TestCase):
    """The field-to-field comparison widget (#167): presence in every bar, the
    embedded column options, and AND/OR prefill round-trip shapes."""

    def _bars(self):
        from common.components import (
            DeviceFilterBar,
            FilterBar,
            PlatformFilterBar,
            PlayEventFilterBar,
            PurchaseFilterBar,
            SessionFilterBar,
        )

        return [
            FilterBar,
            SessionFilterBar,
            PurchaseFilterBar,
            DeviceFilterBar,
            PlatformFilterBar,
            PlayEventFilterBar,
        ]

    def test_widget_present_in_every_bar(self):
        for bar in self._bars():
            html = str(bar(filter_json=""))
            self.assertIn("<field-comparison-set", html, bar.__name__)
            self.assertIn('data-kind="field-comparison"', html, bar.__name__)
            self.assertIn("data-fc-row-template", html, bar.__name__)
            self.assertIn("data-fc-add", html, bar.__name__)

    def test_columns_prop_embedded(self):
        html = str(SessionFilterBar(filter_json=""))
        # The element's columns prop carries the model's comparable columns as
        # JSON (escaped into the attribute); the datetime pair is what the issue's
        # use case compares.
        self.assertIn("timestamp_end", html)
        self.assertIn("timestamp_start", html)
        self.assertIn('mode="AND"', html)

    def test_columns_prop_carries_operators(self):
        # Each column ships its allowed operators as data (#152) so the TS widget
        # renders them directly; the key + a representative ordered op reach the
        # serialized attribute (JSON key/value text survives attribute escaping).
        html = str(SessionFilterBar(filter_json=""))
        self.assertIn("operators", html)
        self.assertIn("LESS_THAN", html)

    def test_no_double_escaped_markup(self):
        # The columns JSON attribute must not introduce escaped element markup.
        html = str(SessionFilterBar(filter_json=""))
        for marker in _ESCAPED_TAG_MARKERS:
            self.assertNotIn(marker, html)

    def test_and_prefill_renders_row(self):
        filter_json = json.dumps(
            {
                "field_comparisons": [
                    {
                        "left": "timestamp_end",
                        "right": "timestamp_start",
                        "modifier": "LESS_THAN",
                    }
                ]
            }
        )
        html = str(SessionFilterBar(filter_json=filter_json))
        # Template row + the prefilled row.
        self.assertGreaterEqual(html.count("data-fc-row"), 2)
        # Saved operator + right column stashed for the TS to restore.
        self.assertIn('data-selected="LESS_THAN"', html)
        self.assertIn('data-selected="timestamp_start"', html)
        # AND mode is the checked toggle.
        self.assertRegex(html, r'value="AND"[^>]*checked="true"')
        self.assertNotRegex(html, r'value="OR"[^>]*checked="true"')

    def test_or_prefill_selects_or_mode(self):
        filter_json = json.dumps(
            {
                "AND": [
                    {
                        "OR": [
                            {
                                "field_comparisons": [
                                    {
                                        "left": "timestamp_end",
                                        "right": "timestamp_start",
                                        "modifier": "LESS_THAN",
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        )
        html = str(SessionFilterBar(filter_json=filter_json))
        self.assertRegex(html, r'value="OR"[^>]*checked="true"')
        self.assertIn('data-selected="LESS_THAN"', html)


class HasComparableGroupTest(TestCase):
    """The ≥2-columns-of-one-group gate shared by the flat bar's comparison field
    and the nested builder's `+ comparison` affordance / row template (#246)."""

    def _column(self, value, group):
        return {"value": value, "label": value.title(), "group": group, "operators": []}

    def test_empty_is_false(self):
        from common.components.filters import has_comparable_group

        self.assertFalse(has_comparable_group([]))

    def test_single_column_is_false(self):
        from common.components.filters import has_comparable_group

        self.assertFalse(has_comparable_group([self._column("a", "number")]))

    def test_two_columns_different_groups_is_false(self):
        from common.components.filters import has_comparable_group

        columns = [self._column("a", "number"), self._column("b", "datetime")]
        self.assertFalse(has_comparable_group(columns))

    def test_two_columns_same_group_is_true(self):
        from common.components.filters import has_comparable_group

        columns = [self._column("a", "number"), self._column("b", "number")]
        self.assertTrue(has_comparable_group(columns))


class ReachableModelsTest(TestCase):
    """The relation-reachable model set the nested builder needs to render any
    relation's child group offline (#193)."""

    def test_reachable_models_is_the_closed_relation_set(self):
        from games.filters import reachable_models

        self.assertEqual(
            set(reachable_models("game")),
            {"game", "session", "purchase", "playevent", "platform", "device"},
        )

    def test_reachable_models_maps_keys_to_filter_classes(self):
        from games.filters import GameFilter, SessionFilter, reachable_models

        models = reachable_models("game")
        self.assertIs(models["game"], GameFilter)
        self.assertIs(models["session"], SessionFilter)

    def test_registry_bundles_fields_and_columns_per_model(self):
        from games.filters import model_field_registry

        registry = model_field_registry("game")
        self.assertEqual(
            set(registry),
            {"game", "session", "purchase", "playevent", "platform", "device"},
        )
        session = registry["session"]
        self.assertIn("fields", session)
        self.assertIn("columns", session)
        # Session's datetime pair reaches the comparison columns.
        column_names = {column["value"] for column in session["columns"]}
        self.assertLessEqual({"timestamp_start", "timestamp_end"}, column_names)
        # The relation entries are discoverable in the field metadata (game→session).
        game_relations = {
            relation["field"]
            for meta in registry["game"]["fields"]
            if meta["kind"] == "relation"
            for relation in meta["relations"]
        }
        self.assertIn("session_filter", game_relations)

    def test_reachable_set_is_the_same_from_any_root(self):
        """The relation graph is strongly connected, so the builder reaches the whole
        model set regardless of which list it is opened from (game/session/…)."""
        from games.filters import reachable_models

        full = {"game", "session", "purchase", "playevent", "platform", "device"}
        for root in full:
            self.assertEqual(set(reachable_models(root)), full, f"root={root}")

    def test_registry_covers_every_reachable_model_and_relation_target(self):
        """The server invariant the client's bundle() fallback relies on: every
        reachable model has a bundle, and every relation target named in any bundle is
        itself a registry key — so a relation descent never lands on a missing model
        (which the client would otherwise silently paper over with the root bundle)."""
        from games.filters import model_field_registry, reachable_models

        for root in ["game", "session", "purchase", "playevent", "platform", "device"]:
            registry = model_field_registry(root)
            self.assertEqual(set(registry), set(reachable_models(root)), f"root={root}")
            for key, bundle in registry.items():
                for meta in bundle["fields"]:
                    for relation in meta["relations"]:
                        self.assertIn(
                            relation["model"].lower(),
                            registry,
                            f"root={root}: relation target {relation['model']!r} "
                            f"(from {key}.{meta['name']}) missing from registry",
                        )


class FilterGroupComparisonTest(TestCase):
    """The nested-builder shell (#246, #193): the multi-model `models` prop + the
    per-model, namespaced templates it emits for the leaf and relation rows."""

    def test_models_prop_carries_every_reachable_model(self):
        from common.components import FilterGroup

        html = str(FilterGroup(model="game"))
        self.assertIn("models=", html)
        # Session's datetime pair — the field-comparison driving use case — reaches
        # the child-model bundle even though the root is game.
        self.assertIn("timestamp_start", html)
        self.assertIn("timestamp_end", html)

    def test_emits_model_namespaced_templates_for_each_reachable_model(self):
        from common.components import FilterGroup

        html = str(FilterGroup(model="game"))
        for key in ("game", "session", "purchase", "playevent", "platform", "device"):
            self.assertIn(f'data-model="{key}"', html)

    def test_emits_comparison_row_template_when_model_has_comparable_group(self):
        from common.components import FilterGroup

        html = str(FilterGroup(model="session"))
        self.assertIn("data-fc-row-template", html)
        # The reused single row's hooks reach the cloned template.
        self.assertIn("data-fc-left", html)

    def test_columns_prop_has_no_double_escaped_markup(self):
        from common.components import FilterGroup

        html = str(FilterGroup(model="session"))
        for marker in _ESCAPED_TAG_MARKERS:
            self.assertNotIn(marker, html)

    def test_emits_chip_and_relation_select_templates(self):
        """Chip + relation-select styling is server-owned (#273): one chip
        template per visual state and one styled <select> template, all
        model-agnostic (emitted once, not per reachable model)."""
        from common.components import FilterGroup

        html = str(FilterGroup(model="game"))
        for state in ("connective-and", "connective-or", "negate-on", "negate-off"):
            self.assertEqual(html.count(f'data-chip-template="{state}"'), 1)
        self.assertEqual(html.count("data-relation-select-template"), 1)
