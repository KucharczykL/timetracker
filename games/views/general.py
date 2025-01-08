from datetime import datetime
from typing import Any, Callable

from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count, ExpressionWrapper, F, Prefetch, Q, Sum, fields
from django.db.models.functions import TruncDate, TruncMonth
from django.db.models.manager import BaseManager
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import redirect, render
from django.urls import reverse

from common.time import available_stats_year_range, dateformat, format_duration
from common.utils import safe_division
from games.models import Edition, Game, Platform, Purchase, Session


def model_counts(request: HttpRequest) -> dict[str, bool]:
    return {
        "game_available": Game.objects.exists(),
        "edition_available": Edition.objects.exists(),
        "platform_available": Platform.objects.exists(),
        "purchase_available": Purchase.objects.exists(),
        "session_count": Session.objects.exists(),
    }


def global_current_year(request: HttpRequest) -> dict[str, int]:
    return {"global_current_year": datetime.now().year}


def use_custom_redirect(
    func: Callable[..., HttpResponse],
) -> Callable[..., HttpResponse]:
    """
    Will redirect to "return_path" session variable if set.
    """

    def wrapper(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        response = func(request, *args, **kwargs)
        if isinstance(response, HttpResponseRedirect) and (
            next_url := request.session.get("return_path")
        ):
            return HttpResponseRedirect(next_url)
        return response

    return wrapper


@login_required
def stats_alltime(request: HttpRequest) -> HttpResponse:
    year = "Alltime"
    this_year_sessions = Session.objects.all().prefetch_related(
        Prefetch("purchase__editions")
    )
    this_year_sessions_with_durations = this_year_sessions.annotate(
        duration=ExpressionWrapper(
            F("timestamp_end") - F("timestamp_start"),
            output_field=fields.DurationField(),
        )
    )
    longest_session = this_year_sessions_with_durations.order_by("-duration").first()
    this_year_games = Game.objects.filter(
        editions__purchase__session__in=this_year_sessions
    ).distinct()
    this_year_games_with_session_counts = this_year_games.annotate(
        session_count=Count("editions__purchase__session"),
    )
    game_highest_session_count = this_year_games_with_session_counts.order_by(
        "-session_count"
    ).first()
    selected_currency = "CZK"
    unique_days = (
        this_year_sessions.annotate(date=TruncDate("timestamp_start"))
        .values("date")
        .distinct()
        .aggregate(dates=Count("date"))
    )
    this_year_played_purchases = Purchase.objects.filter(
        session__in=this_year_sessions
    ).distinct()

    this_year_purchases = Purchase.objects.all()
    this_year_purchases_with_currency = this_year_purchases.select_related("editions")
    this_year_purchases_without_refunded = this_year_purchases_with_currency.filter(
        date_refunded=None
    )
    this_year_purchases_refunded = this_year_purchases_with_currency.refunded()

    this_year_purchases_unfinished_dropped_nondropped = (
        this_year_purchases_without_refunded.filter(date_finished__isnull=True)
        .filter(infinite=False)
        .filter(Q(type=Purchase.GAME) | Q(type=Purchase.DLC))
    )  # do not count battle passes etc.

    this_year_purchases_unfinished = (
        this_year_purchases_unfinished_dropped_nondropped.filter(
            date_dropped__isnull=True
        )
    )
    this_year_purchases_dropped = (
        this_year_purchases_unfinished_dropped_nondropped.filter(
            date_dropped__isnull=False
        )
    )

    this_year_purchases_without_refunded_count = (
        this_year_purchases_without_refunded.count()
    )
    this_year_purchases_unfinished_count = this_year_purchases_unfinished.count()
    this_year_purchases_unfinished_percent = int(
        safe_division(
            this_year_purchases_unfinished_count,
            this_year_purchases_without_refunded_count,
        )
        * 100
    )

    purchases_finished_this_year: BaseManager[Purchase] = Purchase.objects.finished()
    purchases_finished_this_year_released_this_year = (
        purchases_finished_this_year.all().order_by("date_finished")
    )
    purchased_this_year_finished_this_year = (
        this_year_purchases_without_refunded.all()
    ).order_by("date_finished")

    this_year_spendings = this_year_purchases_without_refunded.aggregate(
        total_spent=Sum(F("converted_price"))
    )
    total_spent = this_year_spendings["total_spent"] or 0

    games_with_playtime = (
        Game.objects.filter(editions__purchase__session__in=this_year_sessions)
        .annotate(
            total_playtime=Sum(
                F("editions__purchase__session__duration_calculated")
                + F("editions__purchase__session__duration_manual")
            )
        )
        .values("id", "name", "total_playtime")
    )
    month_playtimes = (
        this_year_sessions.annotate(month=TruncMonth("timestamp_start"))
        .values("month")
        .annotate(playtime=Sum("duration_calculated"))
        .order_by("month")
    )
    for month in month_playtimes:
        month["playtime"] = format_duration(month["playtime"], "%2.0H")

    highest_session_average_game = (
        Game.objects.filter(editions__purchase__session__in=this_year_sessions)
        .annotate(
            session_average=Avg("editions__purchase__session__duration_calculated")
        )
        .order_by("-session_average")
        .first()
    )
    top_10_games_by_playtime = games_with_playtime.order_by("-total_playtime")[:10]
    for game in top_10_games_by_playtime:
        game["formatted_playtime"] = format_duration(game["total_playtime"], "%2.0H")

    total_playtime_per_platform = (
        this_year_sessions.values("purchase__platform__name")
        .annotate(total_playtime=Sum(F("duration_calculated") + F("duration_manual")))
        .annotate(platform_name=F("purchase__platform__name"))
        .values("platform_name", "total_playtime")
        .order_by("-total_playtime")
    )
    for item in total_playtime_per_platform:
        item["formatted_playtime"] = format_duration(item["total_playtime"], "%2.0H")

    backlog_decrease_count = (
        Purchase.objects.all().intersection(purchases_finished_this_year).count()
    )

    first_play_date = "N/A"
    last_play_date = "N/A"
    if this_year_sessions:
        first_session = this_year_sessions.earliest()
        first_play_game = first_session.purchase.first_edition.game
        first_play_date = first_session.timestamp_start.strftime(dateformat)
        last_session = this_year_sessions.latest()
        last_play_game = last_session.purchase.first_edition.game
        last_play_date = last_session.timestamp_start.strftime(dateformat)

    all_purchased_this_year_count = this_year_purchases_with_currency.count()
    all_purchased_refunded_this_year_count: int = this_year_purchases_refunded.count()

    this_year_purchases_dropped_count = this_year_purchases_dropped.count()
    this_year_purchases_dropped_percentage = int(
        safe_division(this_year_purchases_dropped_count, all_purchased_this_year_count)
        * 100
    )
    context = {
        "total_hours": format_duration(
            this_year_sessions.total_duration_unformatted(), "%2.0H"
        ),
        "total_2023_games": this_year_played_purchases.all().count(),
        "top_10_games_by_playtime": top_10_games_by_playtime,
        "year": year,
        "total_playtime_per_platform": total_playtime_per_platform,
        "total_spent": total_spent,
        "total_spent_currency": selected_currency,
        "spent_per_game": int(
            safe_division(total_spent, this_year_purchases_without_refunded_count)
        ),
        "this_year_finished_this_year_count": purchases_finished_this_year_released_this_year.count(),
        "total_sessions": this_year_sessions.count(),
        "unique_days": unique_days["dates"],
        "unique_days_percent": int(unique_days["dates"] / 365 * 100),
        "purchased_unfinished_count": this_year_purchases_unfinished_count,
        "unfinished_purchases_percent": this_year_purchases_unfinished_percent,
        "dropped_count": this_year_purchases_dropped_count,
        "dropped_percentage": this_year_purchases_dropped_percentage,
        "refunded_percent": int(
            safe_division(
                all_purchased_refunded_this_year_count,
                all_purchased_this_year_count,
            )
            * 100
        ),
        "all_purchased_refunded_this_year": this_year_purchases_refunded,
        "all_purchased_refunded_this_year_count": all_purchased_refunded_this_year_count,
        "all_purchased_this_year_count": all_purchased_this_year_count,
        "backlog_decrease_count": backlog_decrease_count,
        "longest_session_time": (
            format_duration(longest_session.duration, "%2.0Hh %2.0mm")
            if longest_session
            else 0
        ),
        "longest_session_game": (
            longest_session.purchase.first_edition.game if longest_session else None
        ),
        "highest_session_count": (
            game_highest_session_count.session_count
            if game_highest_session_count
            else 0
        ),
        "highest_session_count_game": (
            game_highest_session_count if game_highest_session_count else None
        ),
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
        "title": f"{year} Stats",
        "stats_dropdown_year_range": available_stats_year_range(),
    }

    request.session["return_path"] = request.path
    return render(request, "stats.html", context)


@login_required
def stats(request: HttpRequest, year: int = 0) -> HttpResponse:
    selected_year = request.GET.get("year")
    if selected_year:
        return HttpResponseRedirect(reverse("stats_by_year", args=[selected_year]))
    if year == 0:
        return HttpResponseRedirect(reverse("stats_alltime"))
    this_year_sessions = Session.objects.filter(
        timestamp_start__year=year
    ).prefetch_related("purchase__editions")
    this_year_sessions_with_durations = this_year_sessions.annotate(
        duration=ExpressionWrapper(
            F("timestamp_end") - F("timestamp_start"),
            output_field=fields.DurationField(),
        )
    )
    longest_session = this_year_sessions_with_durations.order_by("-duration").first()
    this_year_games = Game.objects.filter(
        edition__purchases__session__in=this_year_sessions
    ).distinct()
    this_year_games_with_session_counts = this_year_games.annotate(
        session_count=Count(
            "edition__purchases__session",
            filter=Q(edition__purchases__session__timestamp_start__year=year),
        )
    )
    game_highest_session_count = this_year_games_with_session_counts.order_by(
        "-session_count"
    ).first()
    selected_currency = "CZK"
    unique_days = (
        this_year_sessions.annotate(date=TruncDate("timestamp_start"))
        .values("date")
        .distinct()
        .aggregate(dates=Count("date"))
    )
    this_year_played_purchases = Purchase.objects.filter(
        session__in=this_year_sessions
    ).distinct()

    this_year_purchases = Purchase.objects.filter(date_purchased__year=year)
    this_year_purchases_with_currency = this_year_purchases.prefetch_related("editions")
    this_year_purchases_without_refunded = this_year_purchases_with_currency.filter(
        date_refunded=None
    ).exclude(ownership_type=Purchase.DEMO)
    this_year_purchases_refunded = this_year_purchases_with_currency.refunded()

    this_year_purchases_unfinished_dropped_nondropped = (
        this_year_purchases_without_refunded.filter(date_finished__isnull=True)
        .filter(infinite=False)
        .filter(Q(type=Purchase.GAME) | Q(type=Purchase.DLC))
    )  # do not count battle passes etc.

    this_year_purchases_unfinished = (
        this_year_purchases_unfinished_dropped_nondropped.filter(
            date_dropped__isnull=True
        )
    )
    this_year_purchases_dropped = (
        this_year_purchases_unfinished_dropped_nondropped.filter(
            date_dropped__isnull=False
        )
    )

    this_year_purchases_without_refunded_count = (
        this_year_purchases_without_refunded.count()
    )
    this_year_purchases_unfinished_count = this_year_purchases_unfinished.count()
    this_year_purchases_unfinished_percent = int(
        safe_division(
            this_year_purchases_unfinished_count,
            this_year_purchases_without_refunded_count,
        )
        * 100
    )

    purchases_finished_this_year = Purchase.objects.filter(date_finished__year=year)
    purchases_finished_this_year_released_this_year = (
        purchases_finished_this_year.filter(editions__year_released=year).order_by(
            "date_finished"
        )
    )
    purchased_this_year_finished_this_year = (
        this_year_purchases_without_refunded.filter(date_finished__year=year)
    ).order_by("date_finished")

    this_year_spendings = this_year_purchases_without_refunded.aggregate(
        total_spent=Sum(F("converted_price"))
    )
    total_spent = this_year_spendings["total_spent"] or 0

    games_with_playtime = (
        Game.objects.filter(edition__purchases__session__in=this_year_sessions)
        .annotate(
            total_playtime=Sum(
                F("edition__purchases__session__duration_calculated")
                + F("edition__purchases__session__duration_manual")
            )
        )
        .values("id", "name", "total_playtime")
    )
    month_playtimes = (
        this_year_sessions.annotate(month=TruncMonth("timestamp_start"))
        .values("month")
        .annotate(playtime=Sum("duration_calculated"))
        .order_by("month")
    )
    for month in month_playtimes:
        month["playtime"] = format_duration(month["playtime"], "%2.0H")

    highest_session_average_game = (
        Game.objects.filter(edition__purchases__session__in=this_year_sessions)
        .annotate(
            session_average=Avg("edition__purchases__session__duration_calculated")
        )
        .order_by("-session_average")
        .first()
    )
    top_10_games_by_playtime = games_with_playtime.order_by("-total_playtime")[:10]
    for game in top_10_games_by_playtime:
        game["formatted_playtime"] = format_duration(game["total_playtime"], "%2.0H")

    total_playtime_per_platform = (
        this_year_sessions.values("purchase__platform__name")
        .annotate(total_playtime=Sum(F("duration_calculated") + F("duration_manual")))
        .annotate(platform_name=F("purchase__platform__name"))
        .values("platform_name", "total_playtime")
        .order_by("-total_playtime")
    )
    for item in total_playtime_per_platform:
        item["formatted_playtime"] = format_duration(item["total_playtime"], "%2.0H")

    backlog_decrease_count = (
        Purchase.objects.filter(date_purchased__year__lt=year)
        .intersection(purchases_finished_this_year)
        .count()
    )

    first_play_date = "N/A"
    last_play_date = "N/A"
    first_play_game = None
    last_play_game = None
    if this_year_sessions:
        first_session = this_year_sessions.earliest()
        first_play_game = first_session.purchase.first_edition.game
        first_play_date = first_session.timestamp_start.strftime(dateformat)
        last_session = this_year_sessions.latest()
        last_play_game = last_session.purchase.first_edition.game
        last_play_date = last_session.timestamp_start.strftime(dateformat)

    all_purchased_this_year_count = this_year_purchases_with_currency.count()
    all_purchased_refunded_this_year_count = this_year_purchases_refunded.count()

    this_year_purchases_dropped_count = this_year_purchases_dropped.count()
    this_year_purchases_dropped_percentage = int(
        safe_division(this_year_purchases_dropped_count, all_purchased_this_year_count)
        * 100
    )
    context = {
        "total_hours": format_duration(
            this_year_sessions.total_duration_unformatted(), "%2.0H"
        ),
        "total_games": this_year_played_purchases.count(),
        "total_2023_games": this_year_played_purchases.filter(
            editions__year_released=year
        ).count(),
        "top_10_games_by_playtime": top_10_games_by_playtime,
        "year": year,
        "total_playtime_per_platform": total_playtime_per_platform,
        "total_spent": total_spent,
        "total_spent_currency": selected_currency,
        "all_purchased_this_year": this_year_purchases_without_refunded,
        "spent_per_game": int(
            safe_division(total_spent, this_year_purchases_without_refunded_count)
        ),
        "all_finished_this_year": purchases_finished_this_year.prefetch_related(
            "editions"
        ).order_by("date_finished"),
        "all_finished_this_year_count": purchases_finished_this_year.count(),
        "this_year_finished_this_year": purchases_finished_this_year_released_this_year.prefetch_related(
            "editions"
        ).order_by("date_finished"),
        "this_year_finished_this_year_count": purchases_finished_this_year_released_this_year.count(),
        "purchased_this_year_finished_this_year": purchased_this_year_finished_this_year.prefetch_related(
            "editions"
        ).order_by("date_finished"),
        "total_sessions": this_year_sessions.count(),
        "unique_days": unique_days["dates"],
        "unique_days_percent": int(unique_days["dates"] / 365 * 100),
        "purchased_unfinished": this_year_purchases_unfinished,
        "purchased_unfinished_count": this_year_purchases_unfinished_count,
        "unfinished_purchases_percent": this_year_purchases_unfinished_percent,
        "dropped_count": this_year_purchases_dropped_count,
        "dropped_percentage": this_year_purchases_dropped_percentage,
        "refunded_percent": int(
            safe_division(
                all_purchased_refunded_this_year_count,
                all_purchased_this_year_count,
            )
            * 100
        ),
        "all_purchased_refunded_this_year": this_year_purchases_refunded,
        "all_purchased_refunded_this_year_count": all_purchased_refunded_this_year_count,
        "all_purchased_this_year": this_year_purchases_with_currency.order_by(
            "date_purchased"
        ),
        "all_purchased_this_year_count": all_purchased_this_year_count,
        "backlog_decrease_count": backlog_decrease_count,
        "longest_session_time": (
            format_duration(longest_session.duration, "%2.0Hh %2.0mm")
            if longest_session
            else 0
        ),
        "longest_session_game": (
            longest_session.purchase.first_edition.game if longest_session else None
        ),
        "highest_session_count": (
            game_highest_session_count.session_count
            if game_highest_session_count
            else 0
        ),
        "highest_session_count_game": (
            game_highest_session_count if game_highest_session_count else None
        ),
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
        "title": f"{year} Stats",
        "month_playtimes": month_playtimes,
        "stats_dropdown_year_range": available_stats_year_range(),
    }

    request.session["return_path"] = request.path
    return render(request, "stats.html", context)


@login_required
def index(request: HttpRequest) -> HttpResponse:
    return redirect("list_sessions")
