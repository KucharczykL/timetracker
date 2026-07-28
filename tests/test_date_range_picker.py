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

from common.components import (
    DateRangeCalendar,
    DateRangeField,
    DateRangePicker,
)
from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DateTimePresentation,
    build_format_profile,
)

_ESCAPED_TAG_MARKERS = ["&lt;div", "&lt;span", "&lt;button", "&lt;input"]
DEFAULT_PRESENTATION = DateTimePresentation(
    DEFAULT_DATE_TIME_FORMAT_PROFILE, "en-us", ZoneInfo("UTC")
)


class DatePartsTest(SimpleTestCase):
    def test_default_format_yields_year_month_day(self):
        parts = DEFAULT_PRESENTATION.profile.segments_for("date")
        self.assertEqual([part.name for part in parts], ["year", "month", "day"])
        self.assertEqual([part.placeholder for part in parts], ["YYYY", "MM", "DD"])
        self.assertEqual([part.input_length for part in parts], [4, 2, 2])
        self.assertEqual([part.display_min_digits for part in parts], [4, 2, 2])


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
            self.assertEqual(side_segments, ["year", "month", "day"])

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

    def test_sides_are_named_by_side_and_part_not_by_field(self):
        """A range side names "from"/"to" plus its part; the group names the
        field. Prefixing every segment with the field name made a screen
        reader repeat it six times across one range field."""

        html = self.render()

        self.assertIn('aria-label="Purchased"', html)
        for side in ("from", "to"):
            for part in ("year", "month", "day"):
                self.assertIn(f'aria-label="{side} {part}"', html)
        self.assertNotIn('aria-label="Purchased from', html)

    def test_renders_calendar_toggle(self):
        html = self.render()
        self.assertIn("data-date-range-calendar-toggle", html)
        self.assertIn('aria-label="Open Purchased calendar"', html)

    def test_no_native_date_inputs(self):
        self.assertNotIn('type="date"', self.render())

    def test_alternate_presentation_controls_segment_order_and_separator(self):
        presentation = DateTimePresentation(
            build_format_profile(
                ("year", "day", "month"),
                hour_cycle="h23",
                display_separator="/",
                segmented_separator="·",
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
            build_format_profile(
                ("year", "day", "month"),
                hour_cycle="h23",
                display_separator=".",
                segmented_separator="·",
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


class CalendarControlButtonTest(SimpleTestCase):
    """Every calendar control comes from ControlButton, and the day-cell looks
    are composed from it in Python (then published to TS by codegen). This is
    the guard against the calendar drifting away from the app's buttons again —
    that drift is what produced 16px-wide month-nav hit areas and
    square-cornered selected/adjacent cells."""

    def test_day_variants_all_come_from_control_button(self):
        from common.components.date_range_picker import CALENDAR_DAY_CLASSES

        self.assertEqual(
            set(CALENDAR_DAY_CLASSES), {"default", "selected", "adjacent", "anchor"}
        )
        for variant, classes in CALENDAR_DAY_CLASSES.items():
            with self.subTest(variant=variant):
                # ControlButton's signature bits: the shared control height and
                # its disabled treatment.
                self.assertIn("min-h-control", classes)
                self.assertIn("disabled:opacity-50", classes)

    def test_every_day_variant_is_rounded(self):
        """Rounding, fill and dimming are orthogonal. Folding them into one
        if/else chain is exactly what left selected and adjacent-month cells
        square, so each variant must carry the radius independently."""
        from common.components.date_range_picker import CALENDAR_DAY_CLASSES

        for variant, classes in CALENDAR_DAY_CLASSES.items():
            with self.subTest(variant=variant):
                self.assertIn("rounded-base", classes)

    def test_selected_variant_never_pairs_a_text_colour_with_the_brand_fill(self):
        """solid-brand carries its own APCA-picked on-colour; adding
        text-heading beside it is a coin flip on stylesheet order and painted
        dark text on the blue fill."""
        from common.components.date_range_picker import CALENDAR_DAY_CLASSES

        for variant in ("selected", "anchor"):
            with self.subTest(variant=variant):
                classes = CALENDAR_DAY_CLASSES[variant]
                self.assertIn("solid-brand", classes)
                self.assertNotIn("text-heading", classes)

    def test_calendar_declares_no_hand_rolled_button_classes(self):
        """The module must not regrow a private *_BUTTON_CLASS table."""
        import common.components.date_range_picker as module

        leftovers = [
            name
            for name in vars(module)
            if name.endswith(("_BUTTON_CLASS", "_PRESET_BUTTON_CLASS"))
        ]
        self.assertEqual(leftovers, [])


class DateRangeCalendarTest(SimpleTestCase):
    def render(self):
        return str(DateRangeCalendar(input_name_prefix="filter-date-purchased"))

    def test_renders_the_day_cell_template_for_the_client_to_clone(self):
        html = self.render()
        self.assertIn('data-date-range-template="day"', html)
        # The prototype is a ControlButton, not a bare <button>.
        self.assertIn("min-h-control", html)

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
        # attachMenu owns visibility via the `hidden` attribute + `data-menu`
        # hook (issue #485 follow-up) — no positioning classes of its own.
        html = self.render()
        self.assertIn('data-menu=""', html)
        self.assertIn('hidden=""', html)

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
        # bar's DateRangePicker keeps toggle, popup calendar, and full footer.
        html = str(
            DateRangePicker(
                presentation=DEFAULT_PRESENTATION,
                label="Started",
                input_name_prefix="filter-started",
            )
        )
        self.assertIn("data-date-range-calendar-toggle", html)
        self.assertIn('data-menu=""', html)
        self.assertIn('hidden=""', html)
        self.assertIn("data-date-range-cancel", html)
        self.assertIn("data-date-range-select", html)
        self.assertNotIn("data-static-calendar", html)

    def test_popup_variant_hosted_in_date_calendar_dropdown(self):
        # issue #485 follow-up: the popup (non-panel) variant is hosted in
        # <drop-down behavior="date-calendar"> so attachMenu owns visibility/
        # positioning/dismiss; the field div is the positioning anchor.
        html = str(
            DateRangePicker(
                presentation=DEFAULT_PRESENTATION,
                label="Started",
                input_name_prefix="filter-started",
            )
        )
        self.assertIn('<drop-down class="block"', html)
        self.assertIn('behavior="date-calendar"', html)
        self.assertIn('data-toggle=""', html)

    def test_panel_variant_has_no_dropdown_wrapper(self):
        # The static-panel variant already lives inside the quick bar's own
        # <drop-down> (the "Label ▾" host) and must not get a second one.
        from common.components import DateRangePanel

        html = str(
            DateRangePanel(
                presentation=DEFAULT_PRESENTATION,
                label="Started",
                input_name_prefix="quick-timestamp_start",
            )
        )
        self.assertNotIn("<drop-down", html)
        self.assertNotIn("data-toggle", html)
