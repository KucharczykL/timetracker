import unittest
from datetime import date

from common.time import daterange


class DaterangeTest(unittest.TestCase):
    def test_daterange_exclusive(self):
        days = daterange(date(2024, 8, 1), date(2024, 8, 3))
        self.assertEqual(
            days,
            [date(2024, 8, 1), date(2024, 8, 2)],
        )

    def test_daterange_inclusive(self):
        days = daterange(date(2024, 8, 1), date(2024, 8, 3), end_inclusive=True)
        self.assertEqual(
            days,
            [date(2024, 8, 1), date(2024, 8, 2), date(2024, 8, 3)],
        )
