from datetime import datetime, timedelta
from typing import Any, Callable

from django.contrib.auth.decorators import login_required
from django.db.models import (
    F,
    Sum,
)

from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.timezone import localtime
from django.utils.timezone import now as timezone_now

from common.layout import render_page
from common.time import format_duration
from games.filters import SessionFilter, filter_url
from games.models import Game, Platform, Purchase, Session
from games.views.stats_content import stats_content
from games.views.stats_data import compute_stats

# The Flowbite-datepicker UMD bundle is declared as media on the YearPicker
# component, so Page() loads it automatically on the stats pages.


def model_counts(request: HttpRequest) -> dict[str, Any]:
    now = timezone_now()
    # Use a contiguous [midnight, next midnight) range in the active timezone
    # instead of day/month/year extracts: a range filter can use an index on
    # timestamp_start, whereas the extracts force a per-row datetime function.
    today = localtime(now).date()
    start_of_today = localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)
    start_of_tomorrow = start_of_today + timedelta(days=1)
    # "Last 7 days" is a calendar-day window (today plus the previous six) so the
    # displayed total matches the list its navbar link points to.
    start_of_window = start_of_today - timedelta(days=6)
    today_played = Session.objects.filter(
        timestamp_start__gte=start_of_today,
        timestamp_start__lt=start_of_tomorrow,
    ).aggregate(time=Sum(F("duration_total")))["time"]
    last_7_played = Session.objects.filter(
        timestamp_start__gte=start_of_window,
        timestamp_start__lt=start_of_tomorrow,
    ).aggregate(time=Sum(F("duration_total")))["time"]

    today_iso = today.isoformat()
    today_url = filter_url(SessionFilter.where(timestamp_start=today_iso))
    last_7_url = filter_url(
        SessionFilter.where(
            timestamp_start__between=(
                (today - timedelta(days=6)).isoformat(),
                today_iso,
            )
        )
    )

    return {
        "game_available": Game.objects.exists(),
        "platform_available": Platform.objects.exists(),
        "purchase_available": Purchase.objects.exists(),
        "session_count": Session.objects.exists(),
        "today_played": format_duration(today_played, "%H h %m m"),
        "last_7_played": format_duration(last_7_played, "%H h %m m"),
        "today_url": today_url,
        "last_7_url": last_7_url,
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
    request.session["return_path"] = request.path
    data = compute_stats(None)
    return render_page(request, stats_content(data), title=data["title"])


@login_required
def stats(request: HttpRequest, year: int = 0) -> HttpResponse:
    selected_year = request.GET.get("year")
    if selected_year:
        return HttpResponseRedirect(
            reverse("games:stats_by_year", args=[selected_year])
        )
    if year == 0:
        return HttpResponseRedirect(reverse("games:stats_alltime"))
    request.session["return_path"] = request.path
    data = compute_stats(year)
    return render_page(request, stats_content(data), title=data["title"])


@login_required
def index(request: HttpRequest) -> HttpResponse:
    return redirect("games:list_sessions")
