"""Request-free stats computation: the data half of the stats page.

`compute_stats(library, year)` computes the metrics and returns them as a
`StatsData` dict; `stats_content` renders that dict. It takes the library
because a status now lives on the library's own `PlayerGame` row, not on the
catalog game. Today it computes from the ORM; this is also the function a future
materialization job would call, and the shape it would populate from a
pre-calculated table.

`year=None` means all-time; otherwise the metrics are scoped to that calendar
year. The two scopes genuinely diverge (different aggregations, and all-time
hides the per-purchase list sections), so the differences are kept explicit.
"""

from datetime import date, datetime, timedelta
from typing import Any, NotRequired, TypedDict

from django.db.models import (
    Avg,
    Count,
    ExpressionWrapper,
    F,
    Max,
    OuterRef,
    Q,
    Subquery,
    Sum,
    fields,
)
from django.db.models.functions import TruncDate, TruncMonth

from common.time import available_stats_year_range
from common.utils import safe_division
from games.models import (
    DONE_STATUSES,
    Game,
    PlayerGameStatus,
    Purchase,
    PurchaseConversionState,
    PurchaseQueryset,
    Session,
    SessionQuerySet,
    UserLibrary,
)


class StatsData(TypedDict):
    # --- always present (both scopes) ---
    year: Any  # int for a year, "Alltime" for all-time
    title: str
    total_hours: timedelta
    total_sessions: int
    unique_days: int
    unique_days_percent: int
    total_year_games: int
    this_year_finished_this_year_count: int
    top_10_games_by_playtime: Any
    total_playtime_per_platform: Any
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
    first_play_date: datetime | None
    last_play_game: Any
    last_play_date: datetime | None
    stats_dropdown_year_range: Any
    # --- per-year only (omitted for all-time, which hides these sections) ---
    total_games: NotRequired[int]
    month_playtimes: NotRequired[Any]
    all_finished_this_year: NotRequired[Any]
    all_finished_this_year_count: NotRequired[int]
    this_year_finished_this_year: NotRequired[Any]
    purchased_this_year_finished_this_year: NotRequired[Any]
    purchased_unfinished: NotRequired[Any]
    all_purchased_this_year: NotRequired[Any]


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
    """The library's tracked games at one of these statuses."""
    return Game.objects.tracked_by(library, tracked__status__in=statuses)


def compute_stats(library: UserLibrary, year: int | None = None) -> StatsData:
    published_currency = (
        PurchaseConversionState.objects.only("published_currency")
        .get(library=library)
        .published_currency
    )
    return _compute_stats_from_scoped_querysets(
        library=library,
        sessions=Session.objects.for_library(library),
        purchases=Purchase.objects.for_library(library),
        year=year,
        fallback_currency=published_currency,
    )


def _compute_stats_from_scoped_querysets(
    *,
    library: UserLibrary,
    sessions: SessionQuerySet,
    purchases: PurchaseQueryset,
    year: int | None,
    fallback_currency: str,
) -> StatsData:
    """Compute metrics without selecting a global Session or Purchase base."""

    library_purchases = purchases
    is_alltime = year is None

    # ── Scope ──────────────────────────────────────────────────────────────
    if is_alltime:
        sessions = sessions.prefetch_related("game")
        without_refunded = library_purchases.filter(date_refunded=None)
        refunded = library_purchases.filter(date_refunded__isnull=False)
        ended_q = Q(games__playevents__ended__isnull=False)
        session_count = Count("sessions")
    else:
        sessions = sessions.filter(timestamp_start__year=year).prefetch_related("game")
        purchases = library_purchases.filter(date_purchased__year=year)
        without_refunded = library_purchases.filter(
            date_refunded=None, date_purchased__year=year
        )
        refunded = library_purchases.exclude(date_refunded=None).filter(
            date_purchased__year=year
        )
        ended_q = Q(games__playevents__ended__year=year)
        session_count = Count(
            "sessions", filter=Q(sessions__timestamp_start__year=year)
        )

    done = _games_at_status(library, *DONE_STATUSES)
    not_finished_q = ~Q(games__in=done) & ~ended_q

    # ── Session superlatives ─────────────────────────────────────────────────
    longest_session = (
        sessions.annotate(
            duration=ExpressionWrapper(
                F("timestamp_end") - F("timestamp_start"),
                output_field=fields.DurationField(),
            )
        )
        .order_by("-duration")
        .first()
    )
    games_in_scope = Game.objects.filter(sessions__in=sessions).distinct()
    highest_session_count_game = (
        games_in_scope.annotate(session_count=session_count)
        .order_by("-session_count")
        .first()
    )
    highest_session_average_game = (
        Game.objects.filter(sessions__in=sessions)
        .annotate(session_average=Avg("sessions__duration_calculated"))
        .order_by("-session_average")
        .first()
    )

    # ── Days played + play range ─────────────────────────────────────────────
    unique_days = (
        sessions.annotate(date=TruncDate("timestamp_start"))
        .values("date")
        .distinct()
        .aggregate(dates=Count("date"))["dates"]
    )
    first_session = sessions.earliest() if sessions.exists() else None
    last_session = sessions.latest() if sessions.exists() else None
    first_play_game = first_session.game if first_session else None
    last_play_game = last_session.game if last_session else None
    first_play_date = first_session.timestamp_start if first_session else None
    last_play_date = last_session.timestamp_start if last_session else None
    if is_alltime:
        unique_days_percent = (
            _days_played_percent(
                unique_days,
                first_session.timestamp_start.date(),
                last_session.timestamp_start.date(),
            )
            if first_session and last_session
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
        #: Not retired too: not_finished_q already excludes it, since
        #: retired is one of the done statuses.
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
            date_finished=Subquery(
                library_purchases.filter(pk=OuterRef("pk"))
                .annotate(max_ended=Max("games__playevents__ended"))
                .values("max_ended")[:1]
            )
        )
        finished_released = finished.order_by("-date_finished")
        backlog_decrease_count = finished.count()
    else:
        finished = (
            library_purchases.finished(library)
            .filter(games__playevents__ended__year=year)
            .annotate(
                game_name=F("games__name"), date_finished=F("games__playevents__ended")
            )
        )
        finished_released = finished.filter(games__year_released=year).order_by(
            "games__playevents__ended"
        )
        purchased_finished = (
            without_refunded.filter(games__playevents__ended__year=year)
            .annotate(
                game_name=F("games__name"), date_finished=F("games__playevents__ended")
            )
            .order_by("games__playevents__ended")
        )
        backlog_decrease_count = (
            library_purchases.filter(date_purchased__year__lt=year)
            .filter(games__in=done)
            .filter(games__playevents__ended__year=year)
            .count()
        )

    # ── Games / platforms by playtime (unified on duration_total) ────────────
    games_with_playtime = (
        Game.objects.filter(sessions__in=sessions)
        .distinct()
        .annotate(total_playtime=Sum("sessions__duration_total"))
        .filter(total_playtime__gt=timedelta(0))
    )
    top_games = games_with_playtime.order_by("-total_playtime")

    # platform_id is carried alongside the name so the stats row can link to a
    # platform-scoped session list (#65).
    total_playtime_per_platform = (
        sessions.values("game__platform__name", "game__platform__id")
        .annotate(playtime=Sum(F("duration_total")))
        .annotate(
            platform_name=F("game__platform__name"),
            platform_id=F("game__platform__id"),
        )
        .values("platform_name", "platform_id", "playtime")
        .order_by("-playtime")
    )

    played_purchases = library_purchases.filter(games__sessions__in=sessions).distinct()
    total_year_games = (
        played_purchases.count()
        if is_alltime
        else played_purchases.filter(games__year_released=year).count()
    )

    year_label = "Alltime" if is_alltime else year
    data: StatsData = {
        "year": year_label,
        "title": f"{year_label} Stats",
        "total_hours": sessions.total_duration_unformatted() or timedelta(0),
        "total_sessions": sessions.count(),
        "unique_days": unique_days,
        "unique_days_percent": unique_days_percent,
        "total_year_games": total_year_games,
        "this_year_finished_this_year_count": finished_released.count(),
        "top_10_games_by_playtime": top_games,
        "total_playtime_per_platform": total_playtime_per_platform,
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
        "longest_session_time": longest_session.duration if longest_session else None,
        "longest_session_game": longest_session.game if longest_session else None,
        "highest_session_count": (
            highest_session_count_game.session_count
            if highest_session_count_game
            else 0
        ),
        "highest_session_count_game": highest_session_count_game,
        "highest_session_average": (
            highest_session_average_game.session_average
            if highest_session_average_game
            else None
        ),
        "highest_session_average_game": highest_session_average_game,
        "first_play_game": first_play_game,
        "first_play_date": first_play_date,
        "last_play_game": last_play_game,
        "last_play_date": last_play_date,
        "stats_dropdown_year_range": available_stats_year_range(),
    }

    if not is_alltime:
        data["total_games"] = games_in_scope.count()
        data["month_playtimes"] = (
            sessions.annotate(month=TruncMonth("timestamp_start"))
            .values("month")
            .annotate(playtime=Sum("duration_total"))
            .order_by("month")
        )
        data["all_finished_this_year"] = finished.prefetch_related("games").order_by(
            "games__playevents__ended"
        )
        data["all_finished_this_year_count"] = finished.count()
        data["this_year_finished_this_year"] = finished_released.prefetch_related(
            "games"
        ).order_by("games__playevents__ended")
        data["purchased_this_year_finished_this_year"] = (
            purchased_finished.prefetch_related("games").order_by(
                "games__playevents__ended"
            )
        )
        data["purchased_unfinished"] = unfinished
        data["all_purchased_this_year"] = purchases.order_by("date_purchased")

    return data
