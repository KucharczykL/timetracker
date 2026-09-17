import unittest
from datetime import date

from common.time import daterange


class StreakTest(unittest.TestCase):
    def test_daterange_exclusive(self):
        d = daterange(date(2024, 8, 1), date(2024, 8, 3))
        self.assertEqual(
            d,
            [date(2024, 8, 1), date(2024, 8, 2)],
        )

    def test_daterange_inclusive(self):
        d = daterange(date(2024, 8, 1), date(2024, 8, 3), end_inclusive=True)
        self.assertEqual(
            d,
            [date(2024, 8, 1), date(2024, 8, 2), date(2024, 8, 3)],
        )
