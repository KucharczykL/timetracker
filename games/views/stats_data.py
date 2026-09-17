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
from enum import Enum, auto
from typing import Any, NotRequired, TypedDict

from django.db.models import (
    F,
    Max,
    Q,
    QuerySet,
    Sum,
)
from django_stubs_ext import WithAnnotations

from common.time import available_stats_year_range
from common.utils import safe_division
from games.filters import GAME_SESSIONS
from games.models import (
    DONE_STATUSES,
    Game,
    PlayerGameStatus,
    PlayerSessionQuerySet,
    Purchase,
    PurchaseConversionState,
    PurchaseQueryset,
    UserLibrary,
)
from games.reads.player_sessions import library_sessions
from games.reads.playthrough_completions import (
    YearScope,
    completion_day,
    completion_exists,
)
from games.reads.playtime import (
    MonthPlaytime,
    PlatformPlaytime,
    PlaytimeBreakdown,
    playtime_by_game,
    playtime_by_month,
    playtime_by_platform,
    total_playtime,
)
from games.reads.session_figures import (
    distinct_days,
    first_play,
    games_in_scope,
    highest_average_game,
    last_play,
    longest_session,
    most_sessions_game,
    session_count,
)


class GamePlaytime(TypedDict):
    total_playtime: timedelta


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
    top_10_games_by_playtime: QuerySet[WithAnnotations[Game, GamePlaytime]]
    total_playtime_per_platform: list[PlatformPlaytime]
    total_spent: Any
    total_spent_currency: str
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
    last_play_game: Any
    last_play_date: date | None
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
    """Which playtime sources a figure reads."""

    #: Sessions, and records wholly in scope.
    BOTH = auto()
    #: A record states no sittings.
    SESSIONS_NO_SITTINGS = auto()
    #: Counts games or purchases with a session.
    SESSIONS_PLAYED_GAMES = auto()
    PURCHASES = auto()
    NOT_A_FIGURE = auto()


type StatsKey = str  # a StatsData key

#: Each key once; the test counts them.
STATS_SOURCE_GROUPS: Mapping[StatsSource, tuple[StatsKey, ...]] = {
    #: Platform rows join through the game's platform.
    StatsSource.BOTH: (
        "total_hours",
        "top_10_games_by_playtime",
        "total_playtime_per_platform",
        "month_playtimes",
    ),
    StatsSource.SESSIONS_NO_SITTINGS: (
        "total_sessions",
        "unique_days",
        "unique_days_percent",
        "longest_session_time",
        "longest_session_game",
        "highest_session_count",
        "highest_session_count_game",
        "highest_session_average",
        "highest_session_average_game",
        "first_play_game",
        "first_play_date",
        "last_play_game",
        "last_play_date",
    ),
    StatsSource.SESSIONS_PLAYED_GAMES: ("total_games", "total_year_games"),
    StatsSource.PURCHASES: (
        "this_year_finished_this_year_count",
        "total_spent",
        "total_spent_currency",
        "spent_per_game",
        "all_purchased_this_year_count",
        "all_purchased_refunded_this_year",
        "all_purchased_refunded_this_year_count",
        "refunded_percent",
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
        "all_purchased_this_year",
    ),
    StatsSource.NOT_A_FIGURE: ("year", "title", "stats_dropdown_year_range"),
}

STATS_SOURCES: Mapping[StatsKey, StatsSource] = {
    key: source for source, keys in STATS_SOURCE_GROUPS.items() for key in keys
}


def _days_played_percent(unique_days: int, first: date, last: date) -> int:
    """Share of days played across the span actually played (all-time).

    Unlike the per-year metric (``unique_days / 365``), the all-time span is the
    real number of days between the first and last session, so the result stays
    meaningful (and ≤100%) across multiple years.
    """
    span = (last - first).days + 1
    if span <= 0:
        return 0
    return min(int(unique_days / span * 100), 100)


def _games_at_status(library: UserLibrary, *statuses: PlayerGameStatus):
    """The library's tracked games at these statuses."""
    return Game.objects.tracked_by(library, tracked__status__in=statuses)


def compute_stats(library: UserLibrary, year: YearScope = None) -> StatsData:
    published_currency = (
        PurchaseConversionState.objects.only("published_currency")
        .get(library=library)
        .published_currency
    )
    return _compute_stats_from_scoped_querysets(
        library=library,
        sessions=library_sessions(library),
        purchases=Purchase.objects.for_library(library),
        year=year,
        fallback_currency=published_currency,
    )


def _compute_stats_from_scoped_querysets(
    *,
    library: UserLibrary,
    sessions: PlayerSessionQuerySet,
    purchases: PurchaseQueryset,
    year: YearScope,
    fallback_currency: str,
) -> StatsData:
    """Compute metrics without selecting a global session or Purchase base.

    Playtime reads library and year, not `sessions`.
    """

    library_purchases = purchases
    is_alltime = year is None

    # ── Scope ──────────────────────────────────────────────────────────────
    if is_alltime:
        without_refunded = library_purchases.filter(date_refunded=None)
        refunded = library_purchases.filter(date_refunded__isnull=False)
    else:
        sessions = sessions.filter(effective_day__year=year)
        purchases = library_purchases.filter(date_purchased__year=year)
        without_refunded = library_purchases.filter(
            date_refunded=None, date_purchased__year=year
        )
        refunded = library_purchases.exclude(date_refunded=None).filter(
            date_purchased__year=year
        )

    completed_q = Q(completion_exists(library, year))
    done = _games_at_status(library, *DONE_STATUSES)
    not_finished_q = ~Q(games__in=done) & ~completed_q

    # ── Session figures, one reader each ─────────────────────────────────────
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

    # ── Spending ─────────────────────────────────────────────────────────────
    spending = without_refunded.aggregate(
        total=Sum(F("converted_price")),
        currency=Max("converted_currency", filter=Q(converted_price__isnull=False)),
    )
    total_spent = spending["total"] or 0
    currency = spending["currency"] or fallback_currency
    without_refunded_count = without_refunded.count()

    # ── Purchase breakdown ───────────────────────────────────────────────────
    only_games_and_dlc = Q(type=Purchase.GAME) | Q(type=Purchase.DLC)
    unfinished = (
        without_refunded.filter(not_finished_q)
        .filter(infinite=False)
        .filter(only_games_and_dlc)
        #: not_finished_q already excludes retired.
        .filter(~Q(games__in=_games_at_status(library, PlayerGameStatus.ABANDONED)))
    )
    dropped = (
        purchases.filter(not_finished_q)
        .filter(
            Q(games__in=_games_at_status(library, PlayerGameStatus.ABANDONED))
            | Q(date_refunded__isnull=False)
        )
        .filter(infinite=False)
        .filter(only_games_and_dlc)
    )
    unfinished_count = unfinished.count()
    dropped_count = dropped.count()
    all_purchased_count = purchases.count()
    refunded_count = refunded.count()

    # ── Finished purchases (scope-divergent) ─────────────────────────────────
    if is_alltime:
        finished = library_purchases.finished(library).annotate(
            date_finished=completion_day(library, None)
        )
        finished_released = finished.order_by(F("date_finished").desc(nulls_last=True))
        backlog_decrease_count = finished.count()
    else:
        #: A dated completion has its marker stated.
        finished = library_purchases.filter(completed_q).annotate(
            date_finished=completion_day(library, year)
        )
        finished_released = (
            finished.filter(games__year_released=year)
            .distinct()
            .order_by(F("date_finished").asc(nulls_last=True))
        )
        purchased_finished = (
            without_refunded.filter(completed_q)
            .annotate(date_finished=completion_day(library, year))
            .order_by(F("date_finished").asc(nulls_last=True))
        )
        backlog_decrease_count = (
            library_purchases.filter(date_purchased__year__lt=year)
            .filter(games__in=done)
            .filter(completed_q)
            #: The done-status join fans a bundle out.
            .distinct()
            .count()
        )

    # ── Games by playtime ────────────────────────────────────────────────────
    #: Visible games: untracked library games still count.
    top_games = (
        Game.objects.visible_to(library)
        .annotate(total_playtime=playtime_by_game(library, year=year))
        .filter(total_playtime__gt=timedelta(0))
        #: Ties need an order, or rows reshuffle.
        .order_by("-total_playtime", "sort_name", "name", "pk")
    )

    played_purchases = library_purchases.filter(
        **{f"games__{GAME_SESSIONS}__in": sessions}
    ).distinct()
    total_year_games = (
        played_purchases.count()
        if is_alltime
        else played_purchases.filter(games__year_released=year).count()
    )

    year_label = "Alltime" if is_alltime else year
    data: StatsData = {
        "year": year_label,
        "title": f"{year_label} Stats",
        "total_hours": total_playtime(library, year=year),
        "total_sessions": session_count(library, year),
        "unique_days": unique_days,
        "unique_days_percent": unique_days_percent,
        "total_year_games": total_year_games,
        "this_year_finished_this_year_count": finished_released.count(),
        "top_10_games_by_playtime": top_games,
        "total_playtime_per_platform": playtime_by_platform(library, year=year),
        "total_spent": total_spent,
        "total_spent_currency": currency,
        "spent_per_game": int(safe_division(total_spent, without_refunded_count)),
        "all_purchased_this_year_count": all_purchased_count,
        "all_purchased_refunded_this_year": refunded,
        "all_purchased_refunded_this_year_count": refunded_count,
        "refunded_percent": int(
            safe_division(refunded_count, all_purchased_count) * 100
        ),
        "dropped_count": dropped_count,
        "dropped_percentage": int(
            safe_division(dropped_count, all_purchased_count) * 100
        ),
        "purchased_unfinished_count": unfinished_count,
        "unfinished_purchases_percent": int(
            safe_division(unfinished_count, without_refunded_count) * 100
        ),
        "backlog_decrease_count": backlog_decrease_count,
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
        "last_play_game": last.game if last else None,
        "last_play_date": last.day if last else None,
        "stats_dropdown_year_range": available_stats_year_range(),
    }

    if year is not None:
        data["total_games"] = games_in_scope(library, year).count()
        data["month_playtimes"] = playtime_by_month(library, year=year)
        data["all_finished_this_year"] = finished.prefetch_related("games").order_by(
            F("date_finished").asc(nulls_last=True)
        )
        data["all_finished_this_year_count"] = finished.count()
        data["this_year_finished_this_year"] = finished_released.prefetch_related(
            "games"
        )
        data["purchased_this_year_finished_this_year"] = (
            purchased_finished.prefetch_related("games")
        )
        data["purchased_unfinished"] = unfinished
        data["all_purchased_this_year"] = purchases.order_by("date_purchased")

    return data
