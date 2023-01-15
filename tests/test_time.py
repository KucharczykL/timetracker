import unittest
from datetime import timedelta

from web.common.util.time import format_duration


class FormatDurationTest(unittest.TestCase):
    def setUp(self) -> None:

        return super().setUp()

    def test_only_days(self):
        delta = timedelta(days=3)
        result = format_duration(delta, "%d days")
        self.assertEqual(result, "3 days")

    def test_only_hours(self):
        delta = timedelta(hours=1)
        result = format_duration(delta, "%H hours")
        self.assertEqual(result, "1 hours")

    def test_overflow_hours(self):
        delta = timedelta(hours=25)
        result = format_duration(delta, "%H hours")
        self.assertEqual(result, "25 hours")

    def test_overflow_hours_into_days(self):
        delta = timedelta(hours=25)
        result = format_duration(delta, "%d days, %H hours")
        self.assertEqual(result, "1 days, 1 hours")

    def test_only_minutes(self):
        delta = timedelta(minutes=34)
        result = format_duration(delta, "%m minutes")
        self.assertEqual(result, "34 minutes")

    def test_only_overflow_minutes(self):
        delta = timedelta(minutes=61)
        result = format_duration(delta, "%m minutes")
        self.assertEqual(result, "61 minutes")

    def test_overflow_minutes_into_hours(self):
        delta = timedelta(minutes=61)
        result = format_duration(delta, "%H hours, %m minutes")
        self.assertEqual(result, "1 hours, 1 minutes")

    def test_only_overflow_seconds(self):
        delta = timedelta(seconds=61)
        result = format_duration(delta, "%s seconds")
        self.assertEqual(result, "61 seconds")

    def test_overflow_seconds_into_minutes(self):
        delta = timedelta(seconds=61)
        result = format_duration(delta, "%m minutes, %s seconds")
        self.assertEqual(result, "1 minutes, 1 seconds")

    def test_only_rawseconds(self):
        delta = timedelta(seconds=5690)
        result = format_duration(delta, "%r total seconds")
        self.assertEqual(result, "5690 total seconds")

    def test_empty(self):
        delta = timedelta()
        result = format_duration(delta, "")
        self.assertEqual(result, "")

    def test_zero(self):
        delta = timedelta()
        result = format_duration(delta, "%r seconds")
        self.assertEqual(result, "0 seconds")

    def test_all_at_once(self):
        delta = timedelta(days=50, hours=10, minutes=34, seconds=24)
        result = format_duration(
            delta, "%d days, %H hours, %m minutes, %s seconds, %r total seconds"
        )
        self.assertEqual(
            result, "50 days, 10 hours, 34 minutes, 24 seconds, 4358064 total seconds"
        )

    def test_negative(self):
        delta = timedelta(hours=-2)
        result = format_duration(delta, "%H hours")
        self.assertEqual(result, "0 hours")

    def test_none(self):
        try:
            format_duration(None)
        except TypeError as exc:
            assert False, f"format_duration(None) raised an exception {exc}"

    def test_number(self):
        self.assertEqual(format_duration(3600, "%H hour"), "1 hour")
