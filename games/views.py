from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from common.time import now as now_with_tz
from common.time import format_duration
from django.conf import settings
from django.shortcuts import redirect, render
from django.db.models import Sum, F
from django.http import HttpResponseRedirect
from django.urls import reverse

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
    return {"stats_dropdown_year_range": range(2022, 2024)}


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
    context["last_session"] = context["sessions"].first()
    context["first_session"] = context["sessions"].last()
    context["sessions_with_notes"] = context["sessions"].exclude(note="")
    return render(request, "view_game.html", context)


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
    year_sessions = Session.objects.filter(
        timestamp_start__gte=first_day_of_year
    ).filter(timestamp_start__lt=last_day_of_year)
    year_purchases = Purchase.objects.filter(session__in=year_sessions).distinct()
    year_purchases_with_playtime = year_purchases.annotate(
        total_playtime=Sum(
            F("session__duration_calculated") + F("session__duration_manual")
        )
    )
    top_10_by_playtime = year_purchases_with_playtime.order_by("-total_playtime")[:10]
    for purchase in top_10_by_playtime:
        purchase.formatted_playtime = format_duration(purchase.total_playtime, "%2.0H")

    total_playtime_per_platform = (
        year_sessions.values("purchase__platform__name")  # Group by platform name
        .annotate(
            total_playtime=Sum(F("duration_calculated") + F("duration_manual"))
        )  # Sum the duration_calculated for each group
        .annotate(platform_name=F("purchase__platform__name"))  # Rename the field
        .values(
            "platform_name", "total_playtime"
        )  # Select the renamed field and total_playtime
        .order_by("-total_playtime")  # Optional: Order by the renamed platform name
    )
    for item in total_playtime_per_platform:
        item["formatted_playtime"] = format_duration(item["total_playtime"], "%2.0H")

    context = {
        "total_hours": format_duration(
            year_sessions.total_duration_unformatted(), "%2.0H"
        ),
        "total_games": year_purchases.count(),
        "total_2023_games": year_purchases.filter(edition__year_released=year).count(),
        "top_10_by_playtime_formatted": top_10_by_playtime,
        "top_10_by_playtime": top_10_by_playtime,
        "year": year,
        "total_playtime_per_platform": total_playtime_per_platform,
    }

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
    return render(request, "add.html", context)


def add_game(request):
    context = {}
    form = GameForm(request.POST or None)
    if form.is_valid():
        form.save()
        return redirect("index")

    context["form"] = form
    context["title"] = "Add New Game"
    return render(request, "add.html", context)


def add_edition(request):
    context = {}
    form = EditionForm(request.POST or None)
    if form.is_valid():
        form.save()
        return redirect("index")

    context["form"] = form
    context["title"] = "Add New Edition"
    return render(request, "add_edition.html", context)


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
