import unittest
from datetime import date

from common.time import daterange, streak_bruteforce


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

    def test_1day_streak(self):
        self.assertEqual(streak_bruteforce([date(2024, 8, 1)])["days"], 1)

    def test_2day_streak(self):
        self.assertEqual(streak_bruteforce([date(2024, 8, 1), date(2024, 8, 2)])["days"], 2)

    def test_31day_streak(self):
        self.assertEqual(
            streak_bruteforce(daterange(date(2024, 8, 1), date(2024, 8, 31), end_inclusive=True))[
                "days"
            ],
            31,
        )

    def test_5day_streak_in_10_days(self):
        d = daterange(
            date(2024, 8, 1), date(2024, 8, 5), end_inclusive=True
        ) + daterange(date(2024, 8, 7), date(2024, 8, 10), end_inclusive=True)
        self.assertEqual(streak_bruteforce(d)["days"], 5)

    def test_10day_streak_in_31_days(self):
        d = daterange(date(2024, 8, 1), date(2024, 8, 31), end_inclusive=True)
        d.remove(date(2024, 8, 8))
        d.remove(date(2024, 8, 15))
        d.remove(date(2024, 8, 21))
        self.assertEqual(streak_bruteforce(d)["days"], 10)

    def test_10day_streak_in_31_days_with_consecutive_missing(self):
        d = daterange(date(2024, 8, 1), date(2024, 8, 31), end_inclusive=True)
        d.remove(date(2024, 8, 4))
        d.remove(date(2024, 8, 5))
        d.remove(date(2024, 8, 6))
        d.remove(date(2024, 8, 7))
        d.remove(date(2024, 8, 8))
        d.remove(date(2024, 8, 15))
        d.remove(date(2024, 8, 21))
        self.assertEqual(streak_bruteforce(d)["days"], 10)
