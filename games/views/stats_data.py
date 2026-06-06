"""Request-free stats computation: the data half of the stats page.

`compute_stats(year)` returns a `StatsData` dict (the documented seam between
*computing* metrics and *rendering* them in `stats_content`). Today it computes
from the ORM; this is also the function a future materialization job would call,
and the shape it would populate from a pre-calculated table.

`year=None` means all-time; otherwise the metrics are scoped to that calendar
year. The two scopes genuinely diverge (different aggregations, and all-time
hides the per-purchase list sections), so the differences are kept explicit.
"""

from datetime import date, timedelta
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

from common.time import available_stats_year_range, dateformat, format_duration
from common.utils import safe_division
from games.models import Game, Purchase, Session


class StatsData(TypedDict):
    # --- always present (both scopes) ---
    year: Any  # int for a year, "Alltime" for all-time
    title: str
    total_hours: str
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
    longest_session_time: Any
    longest_session_game: Any
    highest_session_count: int
    highest_session_count_game: Any
    highest_session_average: Any
    highest_session_average_game: Any
    first_play_game: Any
    first_play_date: str
    last_play_game: Any
    last_play_date: str
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


def compute_stats(year: int | None = None) -> StatsData:
    is_alltime = year is None
    currency = "CZK"

    # ── Scope ──────────────────────────────────────────────────────────────
    if is_alltime:
        sessions = Session.objects.all().prefetch_related("game")
        purchases = Purchase.objects.all()
        without_refunded = Purchase.objects.filter(date_refunded=None)
        refunded = Purchase.objects.refunded()
        ended_q = Q(games__playevents__ended__isnull=False)
        session_count = Count("sessions")
    else:
        sessions = Session.objects.filter(timestamp_start__year=year).prefetch_related(
            "game"
        )
        purchases = Purchase.objects.filter(date_purchased__year=year)
        without_refunded = Purchase.objects.filter(
            date_refunded=None, date_purchased__year=year
        )
        refunded = Purchase.objects.exclude(date_refunded=None).filter(
            date_purchased__year=year
        )
        ended_q = Q(games__playevents__ended__year=year)
        session_count = Count(
            "sessions", filter=Q(sessions__timestamp_start__year=year)
        )

    not_finished_q = ~Q(games__status=Game.Status.FINISHED) & ~ended_q

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
    first_play_date = (
        first_session.timestamp_start.strftime(dateformat) if first_session else "N/A"
    )
    last_play_date = (
        last_session.timestamp_start.strftime(dateformat) if last_session else "N/A"
    )
    if is_alltime:
        unique_days_percent = (
            _days_played_percent(
                unique_days,
                first_session.timestamp_start.date(),
                last_session.timestamp_start.date(),
            )
            if first_session
            else 0
        )
    else:
        unique_days_percent = int(unique_days / 365 * 100)

    # ── Spending ─────────────────────────────────────────────────────────────
    total_spent = without_refunded.aggregate(total=Sum(F("converted_price")))["total"] or 0
    without_refunded_count = without_refunded.count()

    # ── Purchase breakdown ───────────────────────────────────────────────────
    only_games_and_dlc = Q(type=Purchase.GAME) | Q(type=Purchase.DLC)
    unfinished = (
        without_refunded.filter(not_finished_q)
        .filter(infinite=False)
        .filter(only_games_and_dlc)
        .filter(~Q(games__status=Game.Status.RETIRED) & ~Q(games__status=Game.Status.ABANDONED))
    )
    dropped = (
        purchases.filter(not_finished_q)
        .filter(Q(games__status=Game.Status.ABANDONED) | Q(date_refunded__isnull=False))
        .filter(infinite=False)
        .filter(only_games_and_dlc)
    )
    unfinished_count = unfinished.count()
    dropped_count = dropped.count()
    all_purchased_count = purchases.count()
    refunded_count = refunded.count()

    # ── Finished purchases (scope-divergent) ─────────────────────────────────
    if is_alltime:
        finished = Purchase.objects.finished().annotate(
            date_finished=Subquery(
                Purchase.objects.filter(pk=OuterRef("pk"))
                .annotate(max_ended=Max("games__playevents__ended"))
                .values("max_ended")[:1]
            )
        )
        finished_released = finished.order_by("-date_finished")
        backlog_decrease_count = finished.count()
    else:
        finished = (
            Purchase.objects.finished()
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
            Purchase.objects.filter(date_purchased__year__lt=year)
            .filter(games__status=Game.Status.FINISHED)
            .filter(games__playevents__ended__year=year)
            .count()
        )

    # ── Games / platforms by playtime (unified on duration_total) ────────────
    if is_alltime:
        games_with_playtime = (
            Game.objects.filter(sessions__in=sessions)
            .distinct()
            .annotate(total_playtime=Sum("sessions__duration_total"))
            .filter(total_playtime__gt=timedelta(0))
        )
        top_games = games_with_playtime.order_by("-total_playtime")[:10]
    else:
        games_with_playtime = (
            Game.objects.filter(sessions__timestamp_start__year=year)
            .annotate(total_playtime=Sum("sessions__duration_total"))
            .filter(total_playtime__gt=timedelta(0))
        )
        top_games = games_with_playtime.order_by("-total_playtime")

    total_playtime_per_platform = (
        sessions.values("game__platform__name")
        .annotate(playtime=Sum(F("duration_total")))
        .annotate(platform_name=F("game__platform__name"))
        .values("platform_name", "playtime")
        .order_by("-playtime")
    )

    played_purchases = Purchase.objects.filter(games__sessions__in=sessions).distinct()
    total_year_games = (
        played_purchases.count()
        if is_alltime
        else played_purchases.filter(games__year_released=year).count()
    )

    year_label = "Alltime" if is_alltime else year
    data: StatsData = {
        "year": year_label,
        "title": f"{year_label} Stats",
        "total_hours": format_duration(
            sessions.total_duration_unformatted(), "%2.0H"
        ),
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
        "longest_session_time": (
            format_duration(longest_session.duration, "%2.0Hh %2.0mm")
            if longest_session
            else 0
        ),
        "longest_session_game": longest_session.game if longest_session else None,
        "highest_session_count": (
            highest_session_count_game.session_count
            if highest_session_count_game
            else 0
        ),
        "highest_session_count_game": highest_session_count_game,
        "highest_session_average": (
            format_duration(
                highest_session_average_game.session_average, "%2.0Hh %2.0mm"
            )
            if highest_session_average_game
            else 0
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
