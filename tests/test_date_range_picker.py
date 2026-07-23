"""Unit tests for the DateRangePicker component family.

Pins the structural contract of DateRangeField / DateRangeCalendar /
DateRangePicker — segments ordered by the active presentation profile, the
hidden ISO ``{prefix}-min`` / ``{prefix}-max`` inputs that ``filter_bar.js``
serializes, the calendar's preset/footer hooks — and the purchases quick bar
integration that replaced the native-date DateRangeFilter for the Purchased
field.
"""

import json
import re
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase, TestCase

from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DatePartSpec,
    DateTimeFormatProfile,
    DateTimePresentation,
)
from common.components import (
    DateRangeCalendar,
    DateRangeField,
    DateRangePicker,
)

_ESCAPED_TAG_MARKERS = ["&lt;div", "&lt;span", "&lt;button", "&lt;input"]
DEFAULT_PRESENTATION = DateTimePresentation(
    DEFAULT_DATE_TIME_FORMAT_PROFILE, "en-us", ZoneInfo("UTC")
)


class DatePartsTest(SimpleTestCase):
    def test_default_format_yields_day_month_year(self):
        parts = DEFAULT_PRESENTATION.profile.date_parts
        self.assertEqual([part.name for part in parts], ["day", "month", "year"])
        self.assertEqual([part.placeholder for part in parts], ["DD", "MM", "YYYY"])
        self.assertEqual([part.input_length for part in parts], [2, 2, 4])
        self.assertEqual([part.display_min_digits for part in parts], [2, 2, 4])


class DateRangeFieldTest(SimpleTestCase):
    def render(self, **kwargs):
        defaults = {
            "presentation": DEFAULT_PRESENTATION,
            "label": "Purchased",
            "input_name_prefix": "filter-date-purchased",
        }
        defaults.update(kwargs)
        return str(DateRangeField(**defaults))

    def test_renders_hidden_iso_inputs(self):
        html = self.render(min_value="2024-03-15", max_value="2024-09-20")
        self.assertIn('name="filter-date-purchased-min"', html)
        self.assertIn('name="filter-date-purchased-max"', html)
        self.assertIn('data-date-range-hidden="min"', html)
        self.assertIn('data-date-range-hidden="max"', html)
        self.assertIn('value="2024-03-15"', html)
        self.assertIn('value="2024-09-20"', html)

    def test_renders_segments_in_profile_order_for_both_sides(self):
        html = self.render()
        for side in ("min", "max"):
            side_segments = re.findall(
                rf'data-date-part="(\w+)" data-date-side="{side}"', html
            )
            self.assertEqual(side_segments, ["day", "month", "year"])

    def test_segment_placeholders_and_lengths(self):
        html = self.render()
        self.assertEqual(html.count('placeholder="DD"'), 2)
        self.assertEqual(html.count('placeholder="MM"'), 2)
        self.assertEqual(html.count('placeholder="YYYY"'), 2)
        self.assertEqual(html.count('maxlength="2"'), 4)
        self.assertEqual(html.count('maxlength="4"'), 2)
        self.assertEqual(html.count('inputmode="numeric"'), 6)

    def test_prefills_segments_from_iso_values(self):
        html = self.render(min_value="2024-03-15")
        self.assertIn('value="15" data-date-part="day" data-date-side="min"', html)
        self.assertIn('value="03" data-date-part="month" data-date-side="min"', html)
        self.assertIn('value="2024" data-date-part="year" data-date-side="min"', html)
        # The max side stays empty.
        self.assertIn('value="" data-date-part="day" data-date-side="max"', html)

    def test_malformed_iso_value_renders_empty_segments(self):
        html = self.render(min_value="not-a-date")
        self.assertIn('value="" data-date-part="day" data-date-side="min"', html)

    def test_renders_calendar_toggle(self):
        html = self.render()
        self.assertIn("data-date-range-calendar-toggle", html)
        self.assertIn('aria-label="Open Purchased calendar"', html)

    def test_no_native_date_inputs(self):
        self.assertNotIn('type="date"', self.render())

    def test_alternate_presentation_controls_segment_order_and_separator(self):
        presentation = DateTimePresentation(
            DateTimeFormatProfile(
                date_parts=(
                    DatePartSpec("year", "YYYY", input_length=4, display_min_digits=4),
                    DatePartSpec("day", "DD", input_length=2, display_min_digits=1),
                    DatePartSpec("month", "MM", input_length=2, display_min_digits=1),
                ),
                date_separator="/",
                segmented_date_separator="·",
                time_separator=":",
                date_time_separator=" ",
                hour_cycle="h23",
            ),
            "en-us",
            ZoneInfo("UTC"),
        )

        html = self.render(presentation=presentation)

        for side in ("min", "max"):
            side_segments = re.findall(
                rf'data-date-part="(\w+)" data-date-side="{side}"', html
            )
            self.assertEqual(side_segments, ["year", "day", "month"])
        self.assertEqual(html.count(">·</span>"), 4)
        self.assertEqual(html.count('maxlength="2"'), 4)
        self.assertEqual(html.count('maxlength="4"'), 2)
        self.assertEqual(html.count("w-[2ch]"), 4)
        self.assertEqual(html.count("w-[4ch]"), 2)

    def test_alternate_presentation_prefills_each_side_from_iso(self):
        presentation = DateTimePresentation(
            DateTimeFormatProfile(
                date_parts=(
                    DatePartSpec("year", "YYYY", input_length=4, display_min_digits=4),
                    DatePartSpec("day", "DD", input_length=2, display_min_digits=2),
                    DatePartSpec("month", "MM", input_length=2, display_min_digits=2),
                ),
                date_separator=".",
                segmented_date_separator="·",
                time_separator=":",
                date_time_separator=" ",
                hour_cycle="h23",
            ),
            "en-us",
            ZoneInfo("UTC"),
        )

        html = self.render(
            presentation=presentation,
            min_value="2024-03-15",
            max_value="2025-09-20",
        )

        for side, year, day, month in (
            ("min", "2024", "15", "03"),
            ("max", "2025", "20", "09"),
        ):
            self.assertIn(
                f'value="{year}" data-date-part="year" data-date-side="{side}"',
                html,
            )
            self.assertIn(
                f'value="{day}" data-date-part="day" data-date-side="{side}"',
                html,
            )
            self.assertIn(
                f'value="{month}" data-date-part="month" data-date-side="{side}"',
                html,
            )


class DateRangeCalendarTest(SimpleTestCase):
    def render(self):
        return str(DateRangeCalendar(input_name_prefix="filter-date-purchased"))

    def test_renders_all_presets(self):
        html = self.render()
        for preset in (
            "today",
            "yesterday",
            "last_7_days",
            "last_30_days",
            "this_month",
            "last_month",
            "this_year",
        ):
            self.assertIn(f'data-date-range-preset="{preset}"', html)

    def test_renders_footer_buttons(self):
        html = self.render()
        self.assertIn("data-date-range-cancel", html)
        self.assertIn("data-date-range-clear", html)
        self.assertIn("data-date-range-select", html)
        self.assertIn(">Cancel<", html)
        self.assertIn(">Clear<", html)
        self.assertIn(">Select<", html)

    def test_renders_grid_and_navigation_hooks(self):
        html = self.render()
        self.assertIn("data-date-range-grid", html)
        self.assertIn("data-date-range-month-label", html)
        self.assertIn("data-date-range-prev", html)
        self.assertIn("data-date-range-next", html)

    def test_starts_hidden(self):
        self.assertIn('class="hidden absolute', self.render())

    def test_all_buttons_are_type_button(self):
        """No button inside the calendar may submit the surrounding filter form."""
        html = self.render()
        button_count = html.count("<button")
        self.assertEqual(html.count('<button type="button"'), button_count)


class DateRangePickerTest(SimpleTestCase):
    def test_composes_field_and_calendar(self):
        html = str(
            DateRangePicker(
                presentation=DEFAULT_PRESENTATION,
                label="Purchased",
                input_name_prefix="filter-date-purchased",
                min_value="2024-01-01",
                max_value="2024-12-31",
            )
        )
        self.assertIn("<date-range-picker", html)
        self.assertIn('data-input-name-prefix="filter-date-purchased"', html)
        self.assertIn("data-date-range-field", html)
        self.assertIn("data-date-range-calendar", html)
        for marker in _ESCAPED_TAG_MARKERS:
            self.assertNotIn(marker, html)


class QuickBarDateRangePanelTest(TestCase):
    """The purchases quick bar's date facets use the canonical date widget
    (the static-calendar DateRangePanel personality) with the same hidden
    ``-min``/``-max`` ISO inputs the serializer reads."""

    def render(self, filter_json=""):
        from common.components import QuickFilterBar

        return str(
            QuickFilterBar(
                presentation=DEFAULT_PRESENTATION,
                mode="purchases",
                filter_json=filter_json,
                apply_url="/purchases",
            )
        )

    def test_purchased_uses_date_range_panel(self):
        html = self.render()
        self.assertIn("<date-range-picker", html)
        self.assertIn("data-static-calendar", html)
        self.assertIn('data-input-name-prefix="quick-date_purchased"', html)
        # The hidden ISO inputs keep the names the bar serializer reads.
        self.assertIn('name="quick-date_purchased-min"', html)
        self.assertIn('name="quick-date_purchased-max"', html)

    def test_created_uses_date_range_panel(self):
        html = self.render()
        self.assertIn('data-input-name-prefix="quick-created_at"', html)
        self.assertIn('name="quick-created_at-min"', html)
        self.assertIn('name="quick-created_at-max"', html)

    def test_prefilled_between_filter_round_trips_into_picker(self):
        filter_json = json.dumps(
            {
                "date_purchased": {
                    "value": "2024-03-15",
                    "value2": "2024-09-20",
                    "modifier": "BETWEEN",
                }
            }
        )
        html = self.render(filter_json)
        self.assertIn('value="2024-03-15"', html)
        self.assertIn('value="2024-09-20"', html)
        self.assertIn('value="15" data-date-part="day" data-date-side="min"', html)
        self.assertIn('value="20" data-date-part="day" data-date-side="max"', html)


class DateRangePanelTest(SimpleTestCase):
    """The dropdown-panel variant: same element and hidden-input
    contract as DateRangePicker, but no calendar toggle, a statically flowing
    always-visible calendar, and a Clear-only footer."""

    @staticmethod
    def _html() -> str:
        from common.components import DateRangePanel

        return str(
            DateRangePanel(
                presentation=DEFAULT_PRESENTATION,
                label="Started",
                input_name_prefix="quick-timestamp_start",
                min_value="2026-01-01",
                max_value="2026-02-01",
                path=["timestamp_start"],
            )
        )

    def test_static_discriminator_and_serializer_contract(self):
        html = self._html()
        self.assertIn("data-static-calendar", html)
        self.assertIn('data-kind="date"', html)
        self.assertIn('data-path="[&quot;timestamp_start&quot;]"', html)
        self.assertIn('name="quick-timestamp_start-min"', html)
        self.assertIn('name="quick-timestamp_start-max"', html)
        self.assertIn('value="2026-01-01"', html)

    def test_no_toggle_and_calendar_flows_statically(self):
        html = self._html()
        self.assertNotIn("data-date-range-calendar-toggle", html)
        self.assertIn("data-date-range-calendar", html)
        self.assertNotIn("hidden absolute", html)

    def test_footer_is_clear_only(self):
        html = self._html()
        self.assertIn("data-date-range-clear", html)
        self.assertNotIn("data-date-range-cancel", html)
        self.assertNotIn("data-date-range-select", html)

    def test_popup_variant_is_unchanged(self):
        # The panel variant must not leak into the existing widget: the flat
        # bar's DateRangePicker keeps toggle, hidden popup, and full footer.
        html = str(
            DateRangePicker(
                presentation=DEFAULT_PRESENTATION,
                label="Started",
                input_name_prefix="filter-started",
            )
        )
        self.assertIn("data-date-range-calendar-toggle", html)
        self.assertIn("hidden absolute", html)
        self.assertIn("data-date-range-cancel", html)
        self.assertIn("data-date-range-select", html)
        self.assertNotIn("data-static-calendar", html)
