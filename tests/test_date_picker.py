"""Unit tests for the DatePicker component family (issue #485).

Pins the structural contract of DatePickerField / DatePickerCalendar /
DatePicker — segments ordered by the active presentation profile, the
hidden ISO input Django binds under the field's real name, the inert-until-
upgraded field, and the widget/form integration (three profiles, blank
optional values, bound invalid data, canonical field names, edit round-trip).
"""

import re
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase, TestCase

from common.components import DatePicker, DatePickerCalendar, DatePickerField
from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DateTimeFormatProfile,
    DateTimePresentation,
    build_format_profile,
)

_ESCAPED_TAG_MARKERS = ["&lt;div", "&lt;span", "&lt;button", "&lt;input"]
DEFAULT_PRESENTATION = DateTimePresentation(
    DEFAULT_DATE_TIME_FORMAT_PROFILE, "en-us", ZoneInfo("UTC")
)

_DMY_PROFILE = build_format_profile(
    ("day", "month", "year"),
    hour_cycle="h23",
    display_separator="/",
    segmented_separator="/",
)
_MDY_PROFILE = build_format_profile(
    ("month", "day", "year"),
    hour_cycle="h12",
    display_separator="/",
    segmented_separator="/",
)


def _presentation(profile: DateTimeFormatProfile) -> DateTimePresentation:
    return DateTimePresentation(profile, "en-us", ZoneInfo("UTC"))


class DatePickerFieldTest(SimpleTestCase):
    def render(self, **kwargs):
        defaults = {
            "presentation": DEFAULT_PRESENTATION,
            "label": "Purchased",
            "name": "date_purchased",
        }
        defaults.update(kwargs)
        return str(DatePickerField(**defaults))

    def test_renders_hidden_iso_input_named_after_the_field(self):
        html = self.render(value="2024-03-15")
        self.assertIn('name="date_purchased"', html)
        self.assertIn('data-date-picker-hidden=""', html)
        self.assertIn('value="2024-03-15"', html)

    def test_segments_render_in_profile_order_iso(self):
        html = self.render()
        segments = re.findall(r'data-date-part="(\w+)" data-date-side="value"', html)
        self.assertEqual(segments, ["year", "month", "day"])

    def test_segments_render_in_profile_order_dmy(self):
        html = self.render(presentation=_presentation(_DMY_PROFILE))
        segments = re.findall(r'data-date-part="(\w+)" data-date-side="value"', html)
        self.assertEqual(segments, ["day", "month", "year"])

    def test_segments_render_in_profile_order_mdy(self):
        html = self.render(presentation=_presentation(_MDY_PROFILE))
        segments = re.findall(r'data-date-part="(\w+)" data-date-side="value"', html)
        self.assertEqual(segments, ["month", "day", "year"])

    def test_prefills_segments_from_iso_value(self):
        html = self.render(value="2024-03-15")
        self.assertIn('value="2024" data-date-part="year" data-date-side="value"', html)
        self.assertIn('value="03" data-date-part="month" data-date-side="value"', html)
        self.assertIn('value="15" data-date-part="day" data-date-side="value"', html)

    def test_blank_value_renders_empty_segments(self):
        html = self.render(value="")
        self.assertIn('value="" data-date-part="year" data-date-side="value"', html)
        self.assertIn('value="" data-date-part="month" data-date-side="value"', html)
        self.assertIn('value="" data-date-part="day" data-date-side="value"', html)

    def test_malformed_value_renders_empty_segments_not_a_crash(self):
        html = self.render(value="not-a-date")
        self.assertIn('value="" data-date-part="year" data-date-side="value"', html)

    def test_id_goes_on_first_segment_only(self):
        html = self.render(input_id="id_date_purchased")
        self.assertEqual(html.count('id="id_date_purchased"'), 1)
        self.assertIn(
            'id="id_date_purchased" data-date-part="year" data-date-side="value"', html
        )
        # Not on the hidden input (would duplicate the id in the DOM).
        self.assertNotIn('id="id_date_purchased" name="date_purchased"', html)

    def test_no_id_when_not_given(self):
        html = self.render()
        self.assertNotIn(" id=", html)

    def test_renders_calendar_toggle(self):
        html = self.render()
        self.assertIn("data-date-picker-calendar-toggle", html)
        self.assertIn('aria-label="Open Purchased calendar"', html)

    def test_no_native_date_input(self):
        self.assertNotIn('type="date"', self.render())

    def test_role_group_and_aria_label(self):
        html = self.render()
        self.assertIn('role="group"', html)
        self.assertIn('aria-label="Purchased"', html)

    def test_field_name_is_announced_once_not_per_segment(self):
        """The group carries the field name; segments name only their part.

        Repeating it per segment made a screen reader say "Purchased" three
        times before reading a value, and again on every arrow across the row.
        Native ``datetime-local`` names the group once.
        """

        html = self.render()

        self.assertIn('aria-label="Purchased"', html)
        for part in ("year", "month", "day"):
            self.assertIn(f'aria-label="{part}"', html)
            self.assertNotIn(f'aria-label="Purchased {part}"', html)

    def test_required_sets_aria_required(self):
        html = self.render(required=True)
        self.assertIn('aria-required="true"', html)

    def test_not_required_omits_aria_required(self):
        html = self.render(required=False)
        self.assertNotIn("aria-required", html)

    def test_invalid_sets_aria_invalid(self):
        html = self.render(invalid=True)
        self.assertIn('aria-invalid="true"', html)

    def test_not_invalid_omits_aria_invalid(self):
        html = self.render(invalid=False)
        self.assertNotIn("aria-invalid", html)


class DatePickerCalendarTest(SimpleTestCase):
    def render(self):
        return str(DatePickerCalendar(input_name_prefix="date_purchased"))

    def test_no_preset_column(self):
        html = self.render()
        self.assertNotIn("data-date-range-preset", html)
        self.assertNotIn("data-date-range-presets", html)

    def test_footer_is_clear_only(self):
        html = self.render()
        self.assertIn("data-date-range-clear", html)
        self.assertNotIn("data-date-range-cancel", html)
        self.assertNotIn("data-date-range-select", html)
        self.assertIn(">Clear<", html)

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
        html = self.render()
        button_count = html.count("<button")
        self.assertEqual(html.count('<button type="button"'), button_count)


class DatePickerTest(SimpleTestCase):
    def test_composes_field_and_calendar(self):
        html = str(
            DatePicker(
                presentation=DEFAULT_PRESENTATION,
                label="Purchased",
                name="date_purchased",
                value="2024-01-01",
            )
        )
        self.assertIn("<date-picker", html)
        self.assertIn("data-date-picker-field", html)
        self.assertIn("data-date-range-calendar", html)
        for marker in _ESCAPED_TAG_MARKERS:
            self.assertNotIn(marker, html)

    def test_hosted_in_date_calendar_dropdown(self):
        # issue #485 follow-up: hosted in <drop-down behavior="date-calendar">
        # so attachMenu owns visibility/positioning/dismiss (the mobile-overlap
        # fix); the field div is the positioning anchor.
        html = str(
            DatePicker(
                presentation=DEFAULT_PRESENTATION,
                label="Purchased",
                name="date_purchased",
            )
        )
        self.assertIn('<drop-down class="block"', html)
        self.assertIn('behavior="date-calendar"', html)
        self.assertIn('data-toggle=""', html)

    def test_no_noscript_fallback(self):
        """The native fallback is gone (#539).

        It was the only ``<noscript>`` in the app, and the forms it guarded
        cannot be submitted without scripting anyway — their game/games fields
        are required ``SearchSelect`` widgets.
        """

        html = str(
            DatePicker(
                presentation=DEFAULT_PRESENTATION,
                label="Purchased",
                name="date_purchased",
                value="2024-03-15",
            )
        )

        self.assertNotIn("<noscript>", html)
        self.assertNotIn('type="date"', html)

    def test_field_is_inert_until_the_element_upgrades(self):
        """Pre-upgrade the field shows the date but cannot be interacted with.

        The segments carry no ``name``, so they are never submitted — typing
        into them before the engine binds is silently discarded. ``inert``
        (removed in ``bindSegmentField``) makes that window unreachable
        instead, and leaves a script-less page showing the stored date
        read-only rather than blank.
        """

        html = str(
            DatePicker(
                presentation=DEFAULT_PRESENTATION,
                label="Purchased",
                name="date_purchased",
                value="2024-03-15",
            )
        )

        field_open = html.index("data-date-picker-field")
        self.assertIn("inert", html[html.rindex("<div", 0, field_open) : field_open])
        # The value is still rendered: inert hides interaction, not content.
        self.assertIn('value="2024"', html)

    def test_hidden_input_named_after_field_precedes_the_calendar(self):
        html = str(
            DatePicker(
                presentation=DEFAULT_PRESENTATION,
                label="Purchased",
                name="date_purchased",
                value="2024-03-15",
            )
        )
        self.assertLess(
            html.index("data-date-picker-hidden"),
            html.index("data-date-range-calendar"),
        )


class DatePickerWidgetFormTest(TestCase):
    """Form-level integration: value_from_datadict, three profiles round-trip
    identically to the persisted date, blank-optional vs required validation,
    and invalid-POST redisplay behavior."""

    def _form(self, presentation=DEFAULT_PRESENTATION, **kwargs):
        from games.forms import PurchaseForm

        return PurchaseForm(default_currency="USD", presentation=presentation, **kwargs)

    def _game(self):
        from games.models import Game, Platform

        platform = Platform.objects.create(name="PC", icon="pc", group="PC")
        return Game.objects.create(name="Test Game", platform=platform)

    def _valid_data(self, game, **overrides):
        from games.models import Purchase

        data = {
            "games": [game.pk],
            "date_purchased": "2024-03-15",
            "price_currency": "USD",
            "ownership_type": Purchase.DIGITAL,
            "type": Purchase.GAME,
        }
        data.update(overrides)
        return data

    def test_widget_renders_date_picker_component(self):
        form = self._form()
        html = str(form["date_purchased"])
        self.assertIn("<date-picker", html)
        self.assertIn('name="date_purchased"', html)

    def test_persisted_date_identical_regardless_of_display_profile(self):
        """The regression proving date persistence is profile-independent
        (issue #485 acceptance criterion)."""
        for profile in (
            DEFAULT_DATE_TIME_FORMAT_PROFILE,
            _DMY_PROFILE,
            _MDY_PROFILE,
        ):
            game = self._game()
            form = self._form(
                presentation=_presentation(profile),
                data=self._valid_data(game),
            )
            self.assertTrue(form.is_valid(), form.errors)
            purchase = form.save()
            self.assertEqual(str(purchase.date_purchased), "2024-03-15")

    def test_blank_optional_date_submits_as_none(self):
        game = self._game()
        form = self._form(data=self._valid_data(game, date_refunded=""))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNone(form.cleaned_data["date_refunded"])

    def test_required_date_blank_fails_validation(self):
        game = self._game()
        form = self._form(data=self._valid_data(game, date_purchased=""))
        self.assertFalse(form.is_valid())
        self.assertIn("date_purchased", form.errors)

    def test_invalid_post_redisplays_error_and_preserves_hidden_value(self):
        """A syntactically-valid-looking but out-of-range date fails
        DateField validation; the widget must not crash on redisplay and
        must not silently drop the submitted value."""
        game = self._game()
        form = self._form(data=self._valid_data(game, date_purchased="2024-99-99"))
        self.assertFalse(form.is_valid())
        self.assertIn("date_purchased", form.errors)
        html = str(form["date_purchased"])
        self.assertIn("2024-99-99", html)

    def test_unrelated_field_error_preserves_the_full_valid_date(self):
        """A cross-field error elsewhere (missing related_game for a
        non-GAME purchase type) must not blank an already-complete, valid
        date_purchased on redisplay."""
        from games.models import Purchase

        game = self._game()
        form = self._form(
            data=self._valid_data(game, type=Purchase.DLC, related_game="", name="")
        )
        self.assertFalse(form.is_valid())
        self.assertIn("related_game", form.errors)
        self.assertNotIn("date_purchased", form.errors)
        html = str(form["date_purchased"])
        # id="id_date_purchased" lands on the first (year) segment.
        self.assertIn('value="2024" id="id_date_purchased" data-date-part="year"', html)
        self.assertIn('value="03" data-date-part="month" data-date-side="value"', html)
        self.assertIn('value="15" data-date-part="day" data-date-side="value"', html)

    def test_edit_round_trip_preserves_instance_date(self):
        from datetime import date

        from games.models import Purchase

        game = self._game()
        purchase = Purchase.objects.create(price=10, date_purchased=date(2025, 6, 1))
        purchase.games.add(game)

        form = self._form(instance=purchase)
        html = str(form["date_purchased"])
        self.assertIn('value="2025" id="id_date_purchased" data-date-part="year"', html)
        self.assertIn('value="06" data-date-part="month" data-date-side="value"', html)
        self.assertIn('value="01" data-date-part="day" data-date-side="value"', html)

        resubmitted = self._form(
            instance=purchase,
            data=self._valid_data(game, date_purchased="2025-06-01"),
        )
        self.assertTrue(resubmitted.is_valid(), resubmitted.errors)
        saved = resubmitted.save()
        self.assertEqual(str(saved.date_purchased), "2025-06-01")
