"""Behaviour tests for the stats provider (compute_stats).

Locks the metrics that must not change in the view-unification refactor, and
pins the two intentional fixes: all-time "days played %" is span-based, and
games-by-playtime uses duration_total (so manual sessions count).
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from historical_playtime_rows import record_row
from session_rows import duration_only_row, session_row, tracked_run

from games.models import Game, Platform, PlayerSession
from games.reads.playtime import MonthPlaytime, PlatformPlaytime, PlaytimeBreakdown
from games.views.stats_data import (
    STATS_SOURCE_GROUPS,
    STATS_SOURCES,
    StatsData,
    StatsSource,
    _days_played_percent,
    compute_stats,
)

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
        self.library = get_user_model().objects.create_user(username="stats").library
        self.platform = Platform.objects.create(name="PC", icon="pc")
        self.game_a = Game.objects.create(
            library=self.library,
            name="Game A",
            platform=self.platform,
            year_released=2022,
        )
        self.game_b = Game.objects.create(
            library=self.library,
            name="Game B",
            platform=self.platform,
            year_released=2023,
        )

        def dt(y, mo, d, h, mi=0):
            return datetime(y, mo, d, h, mi, tzinfo=TZ)

        # Game A in 2023: 1h + 1.5h on the same day = 2.5h
        session_row(
            self.game_a,
            started_at=dt(2023, 6, 10, 10),
            ended_at=dt(2023, 6, 10, 11),
        )
        session_row(
            self.game_a,
            started_at=dt(2023, 6, 10, 14),
            ended_at=dt(2023, 6, 10, 15, 30),
        )
        # Game B in 2023: 1h tracked + 2h manual (no end) = 3h total
        session_row(
            self.game_b,
            started_at=dt(2023, 7, 1, 20),
            ended_at=dt(2023, 7, 1, 21),
        )
        session_row(
            self.game_b,
            started_at=dt(2023, 7, 2, 12),
            duration_manual=timedelta(hours=2),
        )
        # Game A in 2022 (only counts toward all-time): 2h
        session_row(
            self.game_a,
            started_at=dt(2022, 5, 1, 10),
            ended_at=dt(2022, 5, 1, 12),
        )

    def stats(self, year=None):
        return compute_stats(self.library, year)

    # ── shared metrics (characterization) ──

    def test_session_and_day_counts(self):
        year = self.stats(2023)
        alltime = self.stats(None)
        self.assertEqual(year["total_sessions"], 4)
        self.assertEqual(alltime["total_sessions"], 5)
        self.assertEqual(year["unique_days"], 3)  # 06-10, 07-01, 07-02
        self.assertEqual(alltime["unique_days"], 4)  # + 2022-05-01

    def test_per_year_percent_is_over_365(self):
        self.assertEqual(self.stats(2023)["unique_days_percent"], int(3 / 365 * 100))

    def test_alltime_percent_is_span_based_and_sane(self):
        pct = self.stats(None)["unique_days_percent"]
        self.assertGreaterEqual(pct, 0)
        self.assertLessEqual(pct, 100)

    # ── the duration_total fix ──

    def test_games_by_playtime_includes_manual_sessions(self):
        """In 2023, Game B's manual 2h must count, putting it (3h) above A (2.5h)."""
        top = list(self.stats(2023)["top_10_games_by_playtime"])
        self.assertEqual(top[0].id, self.game_b.id)
        self.assertEqual(top[0].total_playtime, timedelta(hours=3))

    def test_equal_playtimes_order_by_name(self):
        """Ties order by name on every load."""
        tied = Game.objects.create(
            library=self.library, name="Aardvark", platform=self.platform
        )
        session_row(
            tied,
            started_at=datetime(2023, 8, 1, 10, tzinfo=TZ),
            ended_at=datetime(2023, 8, 1, 13, tzinfo=TZ),
        )

        top = list(self.stats(2023)["top_10_games_by_playtime"])

        self.assertEqual([game.id for game in top[:2]], [tied.id, self.game_b.id])

    def test_alltime_playtime_sums_all_years(self):
        """All-time Game A = 2.5h (2023) + 2h (2022) = 4.5h, ahead of B (3h)."""
        top = list(self.stats(None)["top_10_games_by_playtime"])
        self.assertEqual(top[0].id, self.game_a.id)
        self.assertEqual(top[0].total_playtime, timedelta(hours=4, minutes=30))

    # ── section visibility (scope difference preserved) ──

    def test_alltime_omits_per_year_list_sections(self):
        alltime = self.stats(None)
        year = self.stats(2023)
        for key in ("month_playtimes", "all_purchased_this_year", "total_games"):
            self.assertNotIn(key, alltime)
            self.assertIn(key, year)

    def test_year_label(self):
        self.assertEqual(self.stats(None)["year"], "Alltime")
        self.assertEqual(self.stats(2023)["year"], 2023)

    def test_first_and_last_play_values_are_the_rows_days(self):
        """The library's calendar day, which no zone moves at render time."""
        stats = self.stats(2023)

        self.assertEqual(stats["first_play_date"], date(2023, 6, 10))
        self.assertEqual(stats["last_play_date"], date(2023, 7, 2))

    def test_a_duration_only_first_play_prints_its_written_day(self):
        """West of UTC or east, the written day is the day."""
        duration_only_row(
            tracked_run(self.library, self.game_a), date(2023, 1, 5), timedelta(hours=1)
        )

        stats = self.stats(2023)

        self.assertEqual(stats["first_play_date"], date(2023, 1, 5))
        self.assertEqual(stats["first_play_game"], self.game_a)

    def test_the_longest_session_reads_the_effective_duration(self):
        """A Duration-only row enters at its stated time."""
        duration_only_row(
            tracked_run(self.library, self.game_a), date(2023, 9, 1), timedelta(hours=9)
        )

        stats = self.stats(2023)

        self.assertEqual(stats["longest_session_time"], timedelta(hours=9))
        self.assertEqual(stats["longest_session_game"], self.game_a)

    def test_first_and_last_play_values_are_none_without_sessions(self):
        PlayerSession.objects.filter(library=self.library).delete()

        stats = self.stats(2023)

        self.assertIsNone(stats["first_play_date"])
        self.assertIsNone(stats["last_play_date"])


@pytest.mark.django_db
@pytest.mark.untracked_games
def test_an_untracked_library_game_counts_in_top_games(owned_library):
    game = Game.objects.create(library=owned_library, name="Untracked")
    start = datetime(2023, 3, 1, 10, tzinfo=TZ)
    session_row(game, started_at=start, ended_at=start + timedelta(hours=2))

    top = list(compute_stats(owned_library, 2023)["top_10_games_by_playtime"])

    assert [row.id for row in top] == [game.id]


HOUR = timedelta(hours=1)


def test_every_stats_key_states_its_sources_once():
    assert set(STATS_SOURCES) == (
        StatsData.__required_keys__ | StatsData.__optional_keys__
    )
    assert sum(map(len, STATS_SOURCE_GROUPS.values())) == len(STATS_SOURCES)


def _session_figures(stats: StatsData) -> dict[str, object]:
    return {
        key: stats.get(key)
        for key, source in STATS_SOURCES.items()
        if source
        in (StatsSource.SESSIONS_NO_SITTINGS, StatsSource.SESSIONS_PLAYED_GAMES)
    }


@pytest.fixture
def played_and_recorded(owned_library):
    platform = Platform.objects.create(name="PC", icon="pc")
    played = Game.objects.create(library=owned_library, name="Played")
    recorded = Game.objects.create(
        library=owned_library, name="Recorded", platform=platform
    )
    start = datetime(2022, 3, 1, 10, tzinfo=TZ)
    session_row(played, started_at=start, ended_at=start + HOUR)
    return played, recorded, platform


@pytest.mark.django_db
def test_a_contained_record_moves_only_the_playtime_figures(
    owned_library, played_and_recorded
):
    _played, recorded, platform = played_and_recorded
    before = {year: compute_stats(owned_library, year) for year in (2021, 2022, None)}
    record_row(
        [tracked_run(owned_library, recorded)], duration=3 * HOUR, when="2022-06"
    )
    after = {year: compute_stats(owned_library, year) for year in (2021, 2022, None)}

    for year in (2021, 2022, None):
        assert _session_figures(after[year]) == _session_figures(before[year])
    assert after[2021]["total_hours"] == before[2021]["total_hours"]

    this_year = after[2022]
    assert this_year["total_hours"] == PlaytimeBreakdown(HOUR, 3 * HOUR)
    assert [
        (game.name, game.total_playtime)
        for game in this_year["top_10_games_by_playtime"]
    ] == [("Recorded", 3 * HOUR), ("Played", HOUR)]
    assert this_year["total_playtime_per_platform"] == [
        PlatformPlaytime(platform.pk, "PC", PlaytimeBreakdown(timedelta(0), 3 * HOUR)),
        PlatformPlaytime(None, None, PlaytimeBreakdown(HOUR, timedelta(0))),
    ]
    assert this_year["month_playtimes"] == [
        MonthPlaytime(date(2022, 3, 1), PlaytimeBreakdown(HOUR, timedelta(0))),
        MonthPlaytime(date(2022, 6, 1), PlaytimeBreakdown(timedelta(0), 3 * HOUR)),
    ]
    assert after[None]["total_hours"] == PlaytimeBreakdown(HOUR, 3 * HOUR)


@pytest.mark.django_db
def test_a_record_wider_than_a_year_counts_all_time_only(
    owned_library, played_and_recorded
):
    _played, recorded, _platform = played_and_recorded
    record_row(
        [tracked_run(owned_library, recorded)], duration=3 * HOUR, when="2020/2022"
    )

    assert compute_stats(owned_library, 2022)["total_hours"] == PlaytimeBreakdown(
        HOUR, timedelta(0)
    )
    assert [
        game.name
        for game in compute_stats(owned_library, 2022)["top_10_games_by_playtime"]
    ] == ["Played"]
    assert compute_stats(owned_library, None)["total_hours"] == PlaytimeBreakdown(
        HOUR, 3 * HOUR
    )
