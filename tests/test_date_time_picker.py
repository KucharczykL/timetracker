"""Unit tests for the DateTimePicker component family (issue #511).

Pins the structural contract of DateTimeField / DateTimeCalendar /
DateTimePicker — one flat run of date *and* time segments ordered by the active
presentation profile, the day period only where the profile is 12-hour, the
hidden offset-qualified input Django binds under the field's real name, the
inert-until-upgraded field, the copy-to-peer control, and the widget/form
integration (both wire shapes, blank values, edit round-trip).
"""

import re
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from common.components import (
    DateTimeCalendar,
    DateTimeCopyTarget,
    DateTimeField,
    DateTimePicker,
)
from common.components.date_time_picker import datetime_part_values
from common.date_time_presentation import (
    DATE_TIME_FORMAT_PROFILES,
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DateTimeFormatProfile,
    DateTimePresentation,
)
from games.forms import GameStatusChangeForm, SessionForm
from games.models import Game, GameStatusChange

_ESCAPED_TAG_MARKERS = ["&lt;div", "&lt;span", "&lt;button", "&lt;input"]

_ISO_PRESENTATION = DateTimePresentation(
    DEFAULT_DATE_TIME_FORMAT_PROFILE, "en-us", ZoneInfo("UTC")
)
_MDY_12H_PROFILE = DATE_TIME_FORMAT_PROFILES["mdy_12h"]


def _presentation(profile: DateTimeFormatProfile) -> DateTimePresentation:
    return DateTimePresentation(profile, "en-us", ZoneInfo("UTC"))


def _presentation_in(time_zone: str) -> DateTimePresentation:
    return DateTimePresentation(
        DEFAULT_DATE_TIME_FORMAT_PROFILE, "en-us", ZoneInfo(time_zone)
    )


def _segment_order(html: str) -> list[str]:
    return re.findall(r'data-date-part="([a-z_]+)"', html)


class DateTimePartValuesTest(SimpleTestCase):
    def test_reads_the_offset_qualified_shape_the_widget_emits(self):
        buffers, display = datetime_part_values(
            "2026-07-27T14:30:41.123456+02:00", _ISO_PRESENTATION
        )
        self.assertEqual(
            buffers,
            {
                "year": "2026",
                "month": "07",
                "day": "27",
                "hour": "14",
                "minute": "30",
            },
        )
        self.assertEqual(display, {})

    def test_reads_the_naive_shape_a_rejected_submission_posts_back(self):
        buffers, _display = datetime_part_values("2026-03-08T02:30", _ISO_PRESENTATION)
        self.assertEqual(buffers["hour"], "02")
        self.assertEqual(buffers["day"], "08")

    def test_combines_the_hour_and_labels_the_day_period_under_a_12_hour_profile(self):
        buffers, display = datetime_part_values(
            "2026-07-27T14:30:00+00:00", _presentation(_MDY_12H_PROFILE)
        )
        self.assertEqual(buffers["hour"], "02")
        self.assertEqual(buffers["day_period"], "01")
        self.assertEqual(display["day_period"], "PM")

    def test_midnight_and_noon_are_the_ends_of_the_12_hour_cycle(self):
        presentation = _presentation(_MDY_12H_PROFILE)
        midnight, _ = datetime_part_values("2026-07-27T00:05:00+00:00", presentation)
        noon, _ = datetime_part_values("2026-07-27T12:05:00+00:00", presentation)
        self.assertEqual((midnight["hour"], midnight["day_period"]), ("12", "00"))
        self.assertEqual((noon["hour"], noon["day_period"]), ("12", "01"))

    def test_malformed_input_yields_empty_segments_rather_than_raising(self):
        # A bound form can carry anything the user typed.
        self.assertEqual(datetime_part_values("garbage", _ISO_PRESENTATION), ({}, {}))
        self.assertEqual(datetime_part_values("", _ISO_PRESENTATION), ({}, {}))


class DateTimeFieldTest(SimpleTestCase):
    def render(self, **kwargs):
        defaults = {
            "presentation": _ISO_PRESENTATION,
            "label": "Start",
            "name": "timestamp_start",
        }
        defaults.update(kwargs)
        return str(DateTimeField(**defaults))

    def test_renders_the_hidden_input_django_binds_under_the_field_name(self):
        html = self.render(value="2026-07-27T14:30:00+00:00")
        self.assertIn('name="timestamp_start"', html)
        self.assertIn('data-date-time-hidden=""', html)
        self.assertIn('value="2026-07-27T14:30:00+00:00"', html)

    def test_date_and_time_segments_share_one_run_in_profile_order(self):
        self.assertEqual(
            _segment_order(self.render()),
            ["year", "month", "day", "hour", "minute"],
        )
        self.assertEqual(
            _segment_order(self.render(presentation=_presentation(_MDY_12H_PROFILE))),
            ["month", "day", "year", "hour", "minute", "day_period"],
        )

    def test_a_24_hour_profile_renders_no_day_period(self):
        self.assertNotIn("day_period", self.render())

    def test_the_day_period_shows_its_label_and_states_its_buffer(self):
        html = self.render(
            presentation=_presentation(_MDY_12H_PROFILE),
            value="2026-07-27T14:30:00+00:00",
        )
        # The buffer stays numeric so stepping and the wire codec need no
        # special case; only what the user sees is the locale's own label.
        self.assertIn('value="PM"', html)
        self.assertIn('data-typed-digits="01"', html)

    def test_the_field_is_inert_until_the_element_upgrades(self):
        self.assertIn("inert", self.render())

    def test_the_first_segment_carries_the_field_id_so_a_label_focuses_it(self):
        html = self.render(input_id="id_timestamp_start")
        first_segment = re.search(r"<input[^>]*data-date-part=\"year\"[^>]*>", html)
        assert first_segment is not None
        self.assertIn('id="id_timestamp_start"', first_segment.group(0))

    def test_no_copy_control_without_a_target(self):
        self.assertNotIn("data-date-time-copy", self.render())

    def test_the_copy_control_names_its_target_and_its_direction(self):
        html = self.render(
            copy_target=DateTimeCopyTarget(
                "timestamp_end", "Copy start value to end", "↓"
            )
        )
        self.assertIn('data-date-time-copy="timestamp_end"', html)
        self.assertIn('aria-label="Copy start value to end"', html)
        self.assertIn("↓", html)

    def test_the_group_is_named_by_the_row_label_not_by_a_copy_of_it(self):
        # The row's <label for> targets the first segment, which names itself
        # "year", so the label text names nothing — a screen reader announced it
        # as its own object and the group then repeated the same string.
        html = self.render(input_id="id_timestamp_start")
        self.assertIn('aria-labelledby="id_timestamp_start-label"', html)
        self.assertNotIn('aria-label="Start"', html)

    def test_falls_back_to_its_own_label_when_no_row_rendered_one(self):
        # Synthetic pages and the filter tiers render the field without a
        # <label for>, so there is no element to point at.
        html = self.render()
        self.assertIn('aria-label="Start"', html)
        self.assertNotIn("aria-labelledby", html)

    def test_marks_required_and_invalid_on_the_group(self):
        html = self.render(required=True, invalid=True)
        self.assertIn('aria-required="true"', html)
        self.assertIn('aria-invalid="true"', html)

    def test_emits_no_escaped_markup(self):
        html = self.render(value="2026-07-27T14:30:00+00:00")
        for marker in _ESCAPED_TAG_MARKERS:
            self.assertNotIn(marker, html)


class DateTimeCalendarTest(SimpleTestCase):
    def test_footer_offers_now_and_clear_but_no_presets(self):
        html = str(DateTimeCalendar(input_name_prefix="timestamp_start"))
        self.assertIn("data-date-range-now", html)
        self.assertIn("data-date-range-clear", html)
        self.assertNotIn("data-date-range-presets", html)


class DateTimePickerTest(SimpleTestCase):
    def test_the_element_carries_the_field_name_a_copy_control_addresses(self):
        html = str(
            DateTimePicker(
                presentation=_ISO_PRESENTATION,
                label="Start",
                name="timestamp_start",
            )
        )
        self.assertIn("<date-time-field", html)
        self.assertIn('field-name="timestamp_start"', html)

    def test_hosted_in_the_shared_date_calendar_dropdown(self):
        html = str(
            DateTimePicker(
                presentation=_ISO_PRESENTATION, label="Start", name="timestamp_start"
            )
        )
        self.assertIn('behavior="date-calendar"', html)


class DateTimeFieldWidgetTest(TestCase):
    """The Django adapter, through the real forms."""

    def setUp(self):
        from django.contrib.auth import get_user_model

        self.user = get_user_model().objects.create_user(username="datetime-widget")
        self.library = self.user.library

    def _session_form(self, **kwargs):
        return SessionForm(
            library=self.library, presentation=_ISO_PRESENTATION, **kwargs
        )

    def test_blank_optional_value_renders_empty_segments(self):
        html = str(self._session_form()["timestamp_end"])
        self.assertIn('data-date-time-hidden=""', html)
        self.assertNotIn("data-typed-digits", html)

    def test_an_aware_initial_renders_the_accounts_wall_clock(self):
        # Django's prepare_value localizes to the *active* zone before a widget
        # ever sees the value, and that is the presentation's own zone —
        # date_time_presentation_for_request reads it from there. Activating it
        # is what makes this assertion mean anything.
        with timezone.override(ZoneInfo("Pacific/Kiritimati")):
            form = SessionForm(
                library=self.library,
                presentation=_presentation_in("Pacific/Kiritimati"),
                initial={"timestamp_start": datetime(2026, 7, 27, 14, 30, tzinfo=UTC)},
            )
            html = str(form["timestamp_start"])
        # UTC+14: the same instant, as the account's own wall clock — and the
        # offset rides along, so the value names an instant rather than a wall
        # clock a DST fall-back could make ambiguous.
        self.assertIn('value="2026-07-28T04:30:00+14:00"', html)
        self.assertIn('value="04"', html)

    def test_a_rejected_submission_re_renders_what_was_typed(self):
        # The naive shape a DST gap posts back must survive the round trip, or
        # the form would come back empty and eat the user's input.
        form = self._session_form(
            data={
                "game": "",
                "timestamp_start": "2026-03-08T02:30",
                "timestamp_end": "",
                "duration_manual": "",
                "device": "",
                "note": "",
            }
        )
        self.assertFalse(form.is_valid())
        html = str(form["timestamp_start"])
        self.assertIn('value="2026-03-08T02:30"', html)
        self.assertIn('value="02"', html)

    def test_both_session_timestamps_point_their_copy_arrow_at_each_other(self):
        form = self._session_form()
        start = str(form["timestamp_start"])
        end = str(form["timestamp_end"])
        self.assertIn('data-date-time-copy="timestamp_end"', start)
        self.assertIn('data-date-time-copy="timestamp_start"', end)

    def test_a_null_status_change_timestamp_renders_an_empty_field(self):
        # GameStatusChange.timestamp is null=True, so an edit form can be handed
        # None — which must render empty segments rather than the string "None".
        change = GameStatusChange.objects.create(
            game=Game.objects.create(library=self.library, name="Hades"),
            new_status="p",
            timestamp=None,
        )
        html = str(
            GameStatusChangeForm(
                library=self.library, instance=change, presentation=_ISO_PRESENTATION
            )["timestamp"]
        )
        self.assertIn('data-date-time-hidden=""', html)
        self.assertNotIn("None", html)

    def test_a_stored_status_change_timestamp_round_trips_into_segments(self):
        change = GameStatusChange.objects.create(
            game=Game.objects.create(library=self.library, name="Hades"),
            new_status="p",
            timestamp=datetime(2026, 7, 27, 14, 30, tzinfo=UTC),
        )
        with timezone.override(ZoneInfo("UTC")):
            html = str(
                GameStatusChangeForm(
                    library=self.library,
                    instance=change,
                    presentation=_ISO_PRESENTATION,
                )["timestamp"]
            )
        self.assertIn('value="2026-07-27T14:30:00+00:00"', html)
        self.assertIn('value="14"', html)
