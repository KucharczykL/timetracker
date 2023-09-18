from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from common.plots import playtime_over_time_chart
from common.time import now as now_with_tz
from django.conf import settings
from django.shortcuts import redirect, render

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
    return render(request, "add.html", context)


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


def start_session(request, last_session_id: int):
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
        if session.timestamp_end == None and session.duration_manual.seconds == 0:
            session.timestamp_end = datetime.now(ZoneInfo(settings.TIME_ZONE))
            session.unfinished = True

    context["total_duration"] = dataset.total_duration()
    context["dataset"] = dataset
    # cannot use dataset[0] here because that might be only partial QuerySet
    context["last"] = Session.objects.all().order_by("timestamp_start").last()
    # only if 2 or more non-manual sessions exist
    if dataset.filter(timestamp_end__isnull=False).count() >= 2:
        # charts are always oldest->newest
        context["chart"] = playtime_over_time_chart(dataset.order_by("timestamp_start"))

    return render(request, "list_sessions.html", context)


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
