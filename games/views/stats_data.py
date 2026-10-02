"""Request-free stats computation: the data half of the stats page.

`compute_stats(library, year)` computes the metrics as a `StatsData` dict;
`stats_content` renders that dict. The library scopes it: a status is per
library. Today it computes from the ORM; this is also the function a future
materialization job would call, and the shape it would populate from a
pre-calculated table.

`year=None` means all-time; otherwise the metrics are scoped to that calendar
year. The two scopes genuinely diverge (different aggregations, and all-time
hides the per-purchase list sections), so the differences are kept explicit.
"""

from collections.abc import Mapping
from datetime import date, timedelta
from decimal import Decimal
from enum import Enum, auto
from typing import Any, NotRequired, TypedDict

from django.db.models import F, QuerySet

from common.time import available_stats_year_range
from common.utils import safe_division
from games.filters import LibraryEntryFilter
from games.models import LibraryEntry, UserLibrary
from games.reads.calendar import calendar_today
from games.reads.copy_figures import (
    bought_and_finished_copies,
    copies_matching,
    copy_counts,
    finished_copies,
    finished_released_copies,
    paid_for_copy,
    unfinished_copies,
)
from games.reads.days import YearScope
from games.reads.play_figures import (
    PlaySource,
    distinct_days,
    first_play,
    games_in_scope,
    last_play,
)
from games.reads.playthrough_completions import ENTRY_RUNS, completion_day
from games.reads.playtime import (
    GameByPlaytime,
    MonthPlaytime,
    PlatformPlaytime,
    PlaytimeBreakdown,
    games_by_playtime,
    games_by_playtime_queryset,
    playtime_by_month,
    playtime_by_platform,
    total_playtime,
)
from games.reads.purchase_figures import (
    purchase_figures,
    purchases_in_scope,
    purchases_matching,
    refunded_in_scope,
    spending_currency,
)
from games.reads.session_figures import (
    highest_average_game,
    longest_session,
    most_sessions_game,
    session_count,
)


class StatsData(TypedDict):
    # --- always present (both scopes) ---
    year: Any  # int for a year, "Alltime" for all-time
    title: str
    total_hours: PlaytimeBreakdown
    total_sessions: int
    unique_days: int
    unique_days_percent: int
    total_year_games: int
    this_year_finished_this_year_count: int
    games_by_playtime: list[GameByPlaytime]
    games_by_playtime_count: int
    total_playtime_per_platform: list[PlatformPlaytime]
    total_spent: Decimal
    total_spent_currency: str
    #: Unrefunded, at a price nobody knows.
    total_spent_unpriced: int
    #: Unrefunded, an amount and no valuation.
    total_spent_unvalued: int
    spent_per_game: int
    all_purchased_this_year_count: int
    all_purchased_refunded_this_year: Any
    all_purchased_refunded_this_year_count: int
    refunded_percent: int
    dropped_count: int
    dropped_percentage: int
    purchased_unfinished_count: int
    unfinished_purchases_percent: int
    backlog_decrease_count: int
    longest_session_time: timedelta | None
    longest_session_game: Any
    highest_session_count: int
    highest_session_count_game: Any
    highest_session_average: timedelta | None
    highest_session_average_game: Any
    first_play_game: Any
    first_play_date: date | None
    #: A record answered; the row links records.
    first_play_from_record: bool
    last_play_game: Any
    last_play_date: date | None
    last_play_from_record: bool
    stats_dropdown_year_range: Any
    # --- per-year only (omitted for all-time, which hides these sections) ---
    total_games: NotRequired[int]
    month_playtimes: NotRequired[list[MonthPlaytime]]
    all_finished_this_year: NotRequired[Any]
    all_finished_this_year_count: NotRequired[int]
    this_year_finished_this_year: NotRequired[Any]
    purchased_this_year_finished_this_year: NotRequired[Any]
    purchased_unfinished: NotRequired[Any]
    all_purchased_this_year: NotRequired[Any]


class StatsSource(Enum):
    """Which sources a figure reads.

    A count of games reads both sources without being a playtime figure: a
    game enters it through a session or through a record.
    """

    #: Sessions, and a record the figure admits.
    BOTH = auto()
    #: A record states no sittings.
    SESSIONS_NO_SITTINGS = auto()
    PURCHASES = auto()
    #: Live copies on a full Edition.
    ENTRIES = auto()
    NOT_A_FIGURE = auto()


#: Rows one card prints before it offers View all.
LIST_CAP = 5

type StatsKey = str  # a StatsData key

#: Each key once; the test counts them.
STATS_SOURCE_GROUPS: Mapping[StatsSource, tuple[StatsKey, ...]] = {
    #: Platform rows join through the game's platform.
    StatsSource.BOTH: (
        "total_hours",
        "games_by_playtime",
        "games_by_playtime_count",
        "total_playtime_per_platform",
        "month_playtimes",
        "unique_days",
        "unique_days_percent",
        "first_play_game",
        "first_play_date",
        "last_play_game",
        "last_play_date",
        "total_games",
    ),
    StatsSource.SESSIONS_NO_SITTINGS: (
        "total_sessions",
        "longest_session_time",
        "longest_session_game",
        "highest_session_count",
        "highest_session_count_game",
        "highest_session_average",
        "highest_session_average_game",
    ),
    StatsSource.PURCHASES: (
        "total_spent",
        "total_spent_currency",
        "total_spent_unpriced",
        "total_spent_unvalued",
        "spent_per_game",
        "all_purchased_this_year_count",
        "all_purchased_refunded_this_year",
        "all_purchased_refunded_this_year_count",
        "refunded_percent",
        "all_purchased_this_year",
    ),
    StatsSource.ENTRIES: (
        "total_year_games",
        "this_year_finished_this_year_count",
        "dropped_count",
        "dropped_percentage",
        "purchased_unfinished_count",
        "unfinished_purchases_percent",
        "backlog_decrease_count",
        "all_finished_this_year",
        "all_finished_this_year_count",
        "this_year_finished_this_year",
        "purchased_this_year_finished_this_year",
        "purchased_unfinished",
    ),
    StatsSource.NOT_A_FIGURE: (
        "year",
        "title",
        "stats_dropdown_year_range",
        "first_play_from_record",
        "last_play_from_record",
    ),
}

STATS_SOURCES: Mapping[StatsKey, StatsSource] = {
    key: source for source, keys in STATS_SOURCE_GROUPS.items() for key in keys
}


def _days_played_percent(unique_days: int, first: date, last: date) -> int:
    """Share of days played across the span actually played (all-time).

    Unlike the per-year metric (``unique_days / 365``), the all-time span is the
    real number of days between the first and last play, so the result stays
    meaningful (and ≤100%) across multiple years.
    """
    span = (last - first).days + 1
    if span <= 0:
        return 0
    return min(int(unique_days / span * 100), 100)


def compute_stats(library: UserLibrary, year: YearScope = None) -> StatsData:
    """Every figure for one scope."""
    is_alltime = year is None

    # ── Session and day figures, one reader each ─────────────────────────────────────
    longest = longest_session(library, year)
    most_sessions = most_sessions_game(library, year)
    highest_average = highest_average_game(library, year)
    unique_days = distinct_days(library, year)
    first = first_play(library, year)
    last = last_play(library, year)
    if is_alltime:
        unique_days_percent = (
            _days_played_percent(unique_days, first.day, last.day)
            if first and last
            else 0
        )
    else:
        unique_days_percent = int(unique_days / 365 * 100)

    # ── Purchases ────────────────────────────────────────────────────────────
    spending = purchase_figures(library, year)
    currency = spending_currency(library, spending)

    # ── Copies ───────────────────────────────────────────────────────────────
    copies = copy_counts(library, year)

    def finished(entry_filter: LibraryEntryFilter) -> QuerySet[LibraryEntry]:
        """Copies, by their game, with the day."""
        return (
            copies_matching(library, entry_filter)
            .select_related("player_game__game")
            .annotate(date_finished=completion_day(library, year, ENTRY_RUNS))
        )

    finished_released = finished(finished_released_copies(year)).order_by(
        F("date_finished").desc(nulls_last=True)
        if is_alltime
        else F("date_finished").asc(nulls_last=True),
        "pk",
    )

    # ── Games by playtime ────────────────────────────────────────────────────
    #: Visible games: untracked library games still count.
    ranked_games = games_by_playtime(library, year=year, limit=LIST_CAP)
    ranked_games_count = games_by_playtime_queryset(library, year=year).count()

    year_label = "Alltime" if is_alltime else year
    data: StatsData = {
        "year": year_label,
        "title": f"{year_label} Stats",
        "total_hours": total_playtime(library, year=year),
        "total_sessions": session_count(library, year),
        "unique_days": unique_days,
        "unique_days_percent": unique_days_percent,
        "total_year_games": copies.played,
        "this_year_finished_this_year_count": copies.finished_released,
        "games_by_playtime": ranked_games,
        "games_by_playtime_count": ranked_games_count,
        "total_playtime_per_platform": playtime_by_platform(library, year=year),
        "total_spent": spending.total_spent,
        "total_spent_currency": currency,
        "total_spent_unpriced": spending.unpriced,
        "total_spent_unvalued": spending.unvalued,
        "spent_per_game": (
            int(spending.total_spent / spending.valued) if spending.valued else 0
        ),
        "all_purchased_this_year_count": spending.purchases,
        "all_purchased_refunded_this_year": purchases_matching(
            library, refunded_in_scope(year)
        ),
        "all_purchased_refunded_this_year_count": spending.refunded,
        "refunded_percent": int(
            safe_division(spending.refunded, spending.purchases) * 100
        ),
        "dropped_count": copies.dropped,
        "dropped_percentage": int(safe_division(copies.dropped, copies.owned) * 100),
        "purchased_unfinished_count": copies.unfinished,
        "unfinished_purchases_percent": int(
            safe_division(copies.unfinished, copies.owned_held) * 100
        ),
        "backlog_decrease_count": copies.backlog_decrease,
        "longest_session_time": longest.session.effective_duration if longest else None,
        "longest_session_game": longest.game if longest else None,
        "highest_session_count": most_sessions.sessions if most_sessions else 0,
        "highest_session_count_game": most_sessions.game if most_sessions else None,
        "highest_session_average": (
            highest_average.average if highest_average else None
        ),
        "highest_session_average_game": (
            highest_average.game if highest_average else None
        ),
        "first_play_game": first.game if first else None,
        "first_play_date": first.day if first else None,
        "first_play_from_record": bool(first and first.source is PlaySource.RECORD),
        "last_play_game": last.game if last else None,
        "last_play_date": last.day if last else None,
        "last_play_from_record": bool(last and last.source is PlaySource.RECORD),
        "stats_dropdown_year_range": available_stats_year_range(
            calendar_today(library)
        ),
    }

    if year is not None:
        all_finished = finished(finished_copies(year))
        data["total_games"] = games_in_scope(library, year).count()
        data["month_playtimes"] = playtime_by_month(library, year=year)
        data["all_finished_this_year"] = all_finished.order_by(
            F("date_finished").asc(nulls_last=True), "pk"
        )
        data["all_finished_this_year_count"] = all_finished.count()
        data["this_year_finished_this_year"] = finished_released
        data["purchased_this_year_finished_this_year"] = finished(
            bought_and_finished_copies(year)
        ).order_by(F("date_finished").asc(nulls_last=True), "pk")
        data["purchased_unfinished"] = (
            copies_matching(library, unfinished_copies(year))
            .select_related("player_game__game")
            .annotate(paid=paid_for_copy(library))
            .order_by("acquired_lower", "pk")
        )
        data["all_purchased_this_year"] = purchases_matching(
            library, purchases_in_scope(year)
        ).order_by("purchased_lower", "pk")

    return data
