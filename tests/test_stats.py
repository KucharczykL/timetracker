"""Behaviour tests for the stats provider (compute_stats).

Locks the metrics that must not change in the view-unification refactor, and
pins the two intentional fixes: all-time "days played %" is span-based, and
games-by-playtime uses duration_total (so manual sessions count).
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.test import TestCase

from games.models import Game, Platform, Session
from games.views.stats_data import _days_played_percent, compute_stats

TZ = ZoneInfo(settings.TIME_ZONE)


class DaysPlayedPercentTest(TestCase):
    """The span-based all-time percent must differ from the old /365."""

    def test_span_based_differs_from_per_year(self):
        first = datetime(2021, 1, 1).date()
        last = datetime(2023, 12, 31).date()  # ~1095-day span
        # 100 unique days over a 3-year span = ~9%, not the old 100/365 = 27%.
        self.assertEqual(_days_played_percent(100, first, last), 9)

    def test_capped_at_100_and_safe_on_empty_span(self):
        d = datetime(2023, 1, 1).date()
        self.assertEqual(_days_played_percent(5, d, d), 100)  # 1-day span
        self.assertEqual(_days_played_percent(0, d, d), 0)


class ComputeStatsTest(TestCase):
    def setUp(self):
        self.platform = Platform.objects.create(name="PC", icon="pc")
        self.game_a = Game.objects.create(
            name="Game A", platform=self.platform, year_released=2022
        )
        self.game_b = Game.objects.create(
            name="Game B", platform=self.platform, year_released=2023
        )

        def dt(y, mo, d, h, mi=0):
            return datetime(y, mo, d, h, mi, tzinfo=TZ)

        # Game A in 2023: 1h + 1.5h on the same day = 2.5h
        Session.objects.create(
            game=self.game_a,
            timestamp_start=dt(2023, 6, 10, 10),
            timestamp_end=dt(2023, 6, 10, 11),
        )
        Session.objects.create(
            game=self.game_a,
            timestamp_start=dt(2023, 6, 10, 14),
            timestamp_end=dt(2023, 6, 10, 15, 30),
        )
        # Game B in 2023: 1h tracked + 2h manual (no end) = 3h total
        Session.objects.create(
            game=self.game_b,
            timestamp_start=dt(2023, 7, 1, 20),
            timestamp_end=dt(2023, 7, 1, 21),
        )
        Session.objects.create(
            game=self.game_b,
            timestamp_start=dt(2023, 7, 2, 12),
            duration_manual=timedelta(hours=2),
        )
        # Game A in 2022 (only counts toward all-time): 2h
        Session.objects.create(
            game=self.game_a,
            timestamp_start=dt(2022, 5, 1, 10),
            timestamp_end=dt(2022, 5, 1, 12),
        )

    # ── shared metrics (characterization) ──

    def test_session_and_day_counts(self):
        year = compute_stats(2023)
        alltime = compute_stats(None)
        self.assertEqual(year["total_sessions"], 4)
        self.assertEqual(alltime["total_sessions"], 5)
        self.assertEqual(year["unique_days"], 3)  # 06-10, 07-01, 07-02
        self.assertEqual(alltime["unique_days"], 4)  # + 2022-05-01

    def test_per_year_percent_is_over_365(self):
        self.assertEqual(compute_stats(2023)["unique_days_percent"], int(3 / 365 * 100))

    def test_alltime_percent_is_span_based_and_sane(self):
        pct = compute_stats(None)["unique_days_percent"]
        self.assertGreaterEqual(pct, 0)
        self.assertLessEqual(pct, 100)

    # ── the duration_total fix ──

    def test_games_by_playtime_includes_manual_sessions(self):
        """In 2023, Game B's manual 2h must count, putting it (3h) above A (2.5h)."""
        top = list(compute_stats(2023)["top_10_games_by_playtime"])
        self.assertEqual(top[0].id, self.game_b.id)
        self.assertEqual(top[0].total_playtime, timedelta(hours=3))

    def test_alltime_playtime_sums_all_years(self):
        """All-time Game A = 2.5h (2023) + 2h (2022) = 4.5h, ahead of B (3h)."""
        top = list(compute_stats(None)["top_10_games_by_playtime"])
        self.assertEqual(top[0].id, self.game_a.id)
        self.assertEqual(top[0].total_playtime, timedelta(hours=4, minutes=30))

    # ── section visibility (scope difference preserved) ──

    def test_alltime_omits_per_year_list_sections(self):
        alltime = compute_stats(None)
        year = compute_stats(2023)
        for key in ("month_playtimes", "all_purchased_this_year", "total_games"):
            self.assertNotIn(key, alltime)
            self.assertIn(key, year)

    def test_year_label(self):
        self.assertEqual(compute_stats(None)["year"], "Alltime")
        self.assertEqual(compute_stats(2023)["year"], 2023)

    def test_first_and_last_play_values_stay_native_for_rendering(self):
        stats = compute_stats(2023)

        self.assertIsInstance(stats["first_play_date"], datetime)
        self.assertIsInstance(stats["last_play_date"], datetime)
