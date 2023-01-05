import unittest
from web.common.util.time import format_duration
from datetime import timedelta


class FormatDurationTest(unittest.TestCase):
    def setUp(self) -> None:

        return super().setUp()

    def test_only_hours(self):
        delta = timedelta(hours=1)
        result = format_duration(delta, "%H hours")
        self.assertEqual(result, "1 hours")

    def test_only_minutes(self):
        delta = timedelta(minutes=34)
        result = format_duration(delta, "%m minutes")
        self.assertEqual(result, "34 minutes")

    def test_only_overflow_seconds(self):
        delta = timedelta(seconds=61)
        result = format_duration(delta, "%s seconds")
        self.assertEqual(result, "1 seconds")

    def test_only_less_than_minute_seconds(self):
        delta = timedelta(seconds=59)
        result = format_duration(delta)
        self.assertEqual(result, "less than a minute")
