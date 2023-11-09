from common.time import format_duration, now as now_with_tz
from common.utils import safe_division
from datetime import datetime, timedelta
from django.conf import settings
from django.db.models import Sum, F, Count
from django.db.models.functions import TruncDate
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import redirect, render
from django.urls import reverse
from typing import Callable, Any
from zoneinfo import ZoneInfo

from .forms import (
    GameForm,
    PlatformForm,
    PurchaseForm,
    SessionForm,
    EditionForm,
    DeviceForm,
)
from .models import Game, Platform, Purchase, Session, Edition


def model_counts(request):
    return {
        "game_available": Game.objects.count() != 0,
        "edition_available": Edition.objects.count() != 0,
        "platform_available": Platform.objects.count() != 0,
        "purchase_available": Purchase.objects.count() != 0,
        "session_count": Session.objects.count(),
    }


def stats_dropdown_year_range(request):
    return {"stats_dropdown_year_range": range(2018, 2024)}


def add_session(request):
    context = {}
    initial = {}

    now = now_with_tz()
    initial["timestamp_start"] = now

    last = Session.objects.all().last()
    if last != None:
        initial["purchase"] = last.purchase

    form = SessionForm(request.POST or None, initial=initial)
    if form.is_valid():
        form.save()
        return redirect("list_sessions")

    context["title"] = "Add New Session"
    context["form"] = form
    return render(request, "add_session.html", context)


def update_session(request, session_id=None):
    session = Session.objects.get(id=session_id)
    session.finish_now()
    session.save()
    return redirect("list_sessions")


def use_custom_redirect(
    func: Callable[..., HttpResponse]
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


@use_custom_redirect
def edit_session(request, session_id=None):
    context = {}
    session = Session.objects.get(id=session_id)
    form = SessionForm(request.POST or None, instance=session)
    if form.is_valid():
        form.save()
        return redirect("list_sessions")
    context["title"] = "Edit Session"
    context["form"] = form
    return render(request, "add_session.html", context)


@use_custom_redirect
def edit_purchase(request, purchase_id=None):
    context = {}
    purchase = Purchase.objects.get(id=purchase_id)
    form = PurchaseForm(request.POST or None, instance=purchase)
    if form.is_valid():
        form.save()
        return redirect("list_sessions")
    context["title"] = "Edit Purchase"
    context["form"] = form
    return render(request, "add.html", context)


@use_custom_redirect
def edit_game(request, game_id=None):
    context = {}
    purchase = Game.objects.get(id=game_id)
    form = GameForm(request.POST or None, instance=purchase)
    if form.is_valid():
        form.save()
        return redirect("list_sessions")
    context["title"] = "Edit Game"
    context["form"] = form
    return render(request, "add.html", context)


def view_game(request, game_id=None):
    context = {}
    game = Game.objects.get(id=game_id)
    context["title"] = "View Game"
    context["game"] = game
    context["editions"] = Edition.objects.filter(game_id=game_id)
    context["purchases"] = Purchase.objects.filter(edition__game_id=game_id)
    context["sessions"] = Session.objects.filter(
        purchase__edition__game_id=game_id
    ).order_by("-timestamp_start")
    context["total_hours"] = float(
        format_duration(context["sessions"].total_duration_unformatted(), "%2.1H")
    )
    context["session_average"] = round(
        (context["total_hours"]) / int(context["sessions"].count()), 1
    )
    # here first and last is flipped
    # because sessions are ordered from newest to oldest
    # so the most recent are on top
    playrange_start = context["sessions"].last().timestamp_start.strftime("%b %Y")
    playrange_end = context["sessions"].first().timestamp_start.strftime("%b %Y")

    context["playrange"] = (
        playrange_start
        if playrange_start == playrange_end
        else f"{playrange_start} — {playrange_end}"
    )

    context["sessions_with_notes"] = context["sessions"].exclude(note="")
    request.session["return_path"] = request.path
    return render(request, "view_game.html", context)


@use_custom_redirect
def edit_platform(request, platform_id=None):
    context = {}
    purchase = Platform.objects.get(id=platform_id)
    form = PlatformForm(request.POST or None, instance=purchase)
    if form.is_valid():
        form.save()
        return redirect("list_sessions")
    context["title"] = "Edit Platform"
    context["form"] = form
    return render(request, "add.html", context)


@use_custom_redirect
def edit_edition(request, edition_id=None):
    context = {}
    edition = Edition.objects.get(id=edition_id)
    form = EditionForm(request.POST or None, instance=edition)
    if form.is_valid():
        form.save()
        return redirect("list_sessions")
    context["title"] = "Edit Edition"
    context["form"] = form
    return render(request, "add.html", context)


@use_custom_redirect
def start_game_session(request, game_id: int):
    last_session = (
        Session.objects.filter(purchase__edition__game_id=game_id)
        .order_by("-timestamp_start")
        .first()
    )
    session = SessionForm(
        {
            "purchase": last_session.purchase.id,
            "timestamp_start": now_with_tz(),
            "device": last_session.device,
        }
    )
    session.save()
    return redirect("list_sessions")


def start_session_same_as_last(request, last_session_id: int):
    last_session = Session.objects.get(id=last_session_id)
    session = SessionForm(
        {
            "purchase": last_session.purchase.id,
            "timestamp_start": now_with_tz(),
            "device": last_session.device,
        }
    )
    session.save()
    return redirect("list_sessions")


# def delete_session(request, session_id=None):
#     session = Session.objects.get(id=session_id)
#     session.delete()
#     return redirect("list_sessions")


def list_sessions(
    request,
    filter="",
    purchase_id="",
    platform_id="",
    game_id="",
    edition_id="",
    ownership_type: str = "",
):
    context = {}
    context["title"] = "Sessions"

    if filter == "purchase":
        dataset = Session.objects.filter(purchase=purchase_id)
        context["purchase"] = Purchase.objects.get(id=purchase_id)
    elif filter == "platform":
        dataset = Session.objects.filter(purchase__platform=platform_id)
        context["platform"] = Platform.objects.get(id=platform_id)
    elif filter == "edition":
        dataset = Session.objects.filter(purchase__edition=edition_id)
        context["edition"] = Edition.objects.get(id=edition_id)
    elif filter == "game":
        dataset = Session.objects.filter(purchase__edition__game=game_id)
        context["game"] = Game.objects.get(id=game_id)
    elif filter == "ownership_type":
        dataset = Session.objects.filter(purchase__ownership_type=ownership_type)
        context["ownership_type"] = dict(Purchase.OWNERSHIP_TYPES)[ownership_type]
    elif filter == "recent":
        current_year = datetime.now().year
        first_day_of_year = datetime(current_year, 1, 1)
        dataset = Session.objects.filter(
            timestamp_start__gte=first_day_of_year
        ).order_by("-timestamp_start")
        context["title"] = "This year"
    else:
        # by default, sort from newest to oldest
        dataset = Session.objects.all().order_by("-timestamp_start")

    for session in dataset:
        if session.timestamp_end == None and session.duration_manual == timedelta(
            seconds=0
        ):
            session.timestamp_end = datetime.now(ZoneInfo(settings.TIME_ZONE))
            session.unfinished = True

    context["total_duration"] = dataset.total_duration_formatted()
    context["dataset"] = dataset
    # cannot use dataset[0] here because that might be only partial QuerySet
    context["last"] = Session.objects.all().order_by("timestamp_start").last()

    return render(request, "list_sessions.html", context)


def stats(request, year: int = 0):
    selected_year = request.GET.get("year")
    if selected_year:
        return HttpResponseRedirect(reverse("stats_by_year", args=[selected_year]))
    if year == 0:
        year = now_with_tz().year
    first_day_of_year = datetime(year, 1, 1)
    last_day_of_year = datetime(year + 1, 1, 1)
    year_sessions = Session.objects.filter(timestamp_start__year=year)
    unique_days = (
        year_sessions.annotate(date=TruncDate("timestamp_start"))
        .values("date")
        .distinct()
        .aggregate(dates=Count("date"))
    )
    year_played_purchases = Purchase.objects.filter(
        session__in=year_sessions
    ).distinct()

    selected_currency = "CZK"
    all_purchased_this_year = (
        Purchase.objects.filter(date_purchased__year=year)
        .filter(price_currency__exact=selected_currency)
        .order_by("date_purchased")
    )
    all_purchased_without_refunded_this_year = all_purchased_this_year.not_refunded()
    all_purchased_refunded_this_year = (
        Purchase.objects.filter(date_purchased__year=year)
        .filter(price_currency__exact=selected_currency)
        .refunded()
        .order_by("date_purchased")
    )

    purchased_unfinished = all_purchased_without_refunded_this_year.filter(
        date_finished__isnull=True
    )

    unfinished_purchases_percent = int(
        safe_division(
            purchased_unfinished.count(), all_purchased_refunded_this_year.count()
        )
        * 100
    )

    all_finished_this_year = Purchase.objects.filter(date_finished__year=year).order_by(
        "date_finished"
    )
    this_year_finished_this_year = (
        Purchase.objects.filter(date_finished__year=year)
        .filter(edition__year_released=year)
        .order_by("date_finished")
    )
    purchased_this_year_finished_this_year = (
        all_purchased_without_refunded_this_year.filter(
            date_finished__year=year
        ).order_by("date_finished")
    )

    this_year_spendings = all_purchased_without_refunded_this_year.aggregate(
        total_spent=Sum(F("price"))
    )
    total_spent = this_year_spendings["total_spent"]

    games_with_playtime = (
        Game.objects.filter(edition__purchase__session__in=year_sessions)
        .annotate(
            total_playtime=Sum(
                F("edition__purchase__session__duration_calculated")
                + F("edition__purchase__session__duration_manual")
            )
        )
        .values("id", "name", "total_playtime")
    )
    top_10_games_by_playtime = games_with_playtime.order_by("-total_playtime")[:10]
    for game in top_10_games_by_playtime:
        game["formatted_playtime"] = format_duration(game["total_playtime"], "%2.0H")

    total_playtime_per_platform = (
        year_sessions.values("purchase__platform__name")
        .annotate(total_playtime=Sum(F("duration_calculated") + F("duration_manual")))
        .annotate(platform_name=F("purchase__platform__name"))
        .values("platform_name", "total_playtime")
        .order_by("-total_playtime")
    )
    for item in total_playtime_per_platform:
        item["formatted_playtime"] = format_duration(item["total_playtime"], "%2.0H")

    backlog_decrease_count = (
        Purchase.objects.filter(date_purchased__year__lt=year)
        .filter(date_finished__year=year)
        .count()
    )

    context = {
        "total_hours": format_duration(
            year_sessions.total_duration_unformatted(), "%2.0H"
        ),
        "total_games": year_played_purchases.count(),
        "total_2023_games": year_played_purchases.filter(
            edition__year_released=year
        ).count(),
        "top_10_games_by_playtime": top_10_games_by_playtime,
        "year": year,
        "total_playtime_per_platform": total_playtime_per_platform,
        "total_spent": total_spent,
        "total_spent_currency": selected_currency,
        "all_purchased_this_year": all_purchased_without_refunded_this_year,
        "spent_per_game": int(
            safe_division(total_spent, all_purchased_without_refunded_this_year.count())
        ),
        "all_finished_this_year": all_finished_this_year,
        "this_year_finished_this_year": this_year_finished_this_year,
        "purchased_this_year_finished_this_year": purchased_this_year_finished_this_year,
        "total_sessions": year_sessions.count(),
        "unique_days": unique_days["dates"],
        "unique_days_percent": int(unique_days["dates"] / 365 * 100),
        "purchased_unfinished": purchased_unfinished,
        "unfinished_purchases_percent": unfinished_purchases_percent,
        "refunded_percent": int(
            safe_division(
                all_purchased_refunded_this_year.count(),
                all_purchased_this_year.count(),
            )
            * 100
        ),
        "all_purchased_refunded_this_year": all_purchased_refunded_this_year,
        "all_purchased_this_year": all_purchased_this_year,
        "backlog_decrease_count": backlog_decrease_count,
    }

    request.session["return_path"] = request.path
    return render(request, "stats.html", context)


def add_purchase(request):
    context = {}
    now = datetime.now()
    initial = {"date_purchased": now}
    form = PurchaseForm(request.POST or None, initial=initial)
    if form.is_valid():
        form.save()
        return redirect("index")

    context["form"] = form
    context["title"] = "Add New Purchase"
    context["script_name"] = "add_purchase.js"
    return render(request, "add.html", context)


def add_game(request):
    context = {}
    form = GameForm(request.POST or None)
    if form.is_valid():
        form.save()
        return redirect("index")

    context["form"] = form
    context["title"] = "Add New Game"
    context["script_name"] = "add_game.js"
    return render(request, "add.html", context)


def add_edition(request):
    context = {}
    form = EditionForm(request.POST or None)
    if form.is_valid():
        form.save()
        return redirect("index")

    context["form"] = form
    context["title"] = "Add New Edition"
    context["script_name"] = "add_edition.js"
    return render(request, "add.html", context)


def add_platform(request):
    context = {}
    form = PlatformForm(request.POST or None)
    if form.is_valid():
        form.save()
        return redirect("index")

    context["form"] = form
    context["title"] = "Add New Platform"
    return render(request, "add.html", context)


def add_device(request):
    context = {}
    form = DeviceForm(request.POST or None)
    if form.is_valid():
        form.save()
        return redirect("index")

    context["form"] = form
    context["title"] = "Add New Device"
    return render(request, "add.html", context)


def index(request):
    return redirect("list_sessions_recent")
