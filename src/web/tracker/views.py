from datetime import datetime
from zoneinfo import ZoneInfo

from common.util.plots import playtime_over_time_chart
from common.util.time import now as now_with_tz
from django.conf import settings
from django.shortcuts import redirect, render

from .forms import GameForm, PlatformForm, PurchaseForm, SessionForm
from .models import Game, Platform, Purchase, Session


def model_counts(request):
    return {
        "game_available": Game.objects.count() != 0,
        "platform_available": Platform.objects.count() != 0,
        "purchase_available": Purchase.objects.count() != 0,
        "session_count": Session.objects.count(),
    }


def add_session(request):
    context = {}
    now = now_with_tz()
    last = Session.objects.all().last()
    initial = {"timestamp_start": now, "purchase": last.purchase}
    form = SessionForm(request.POST or None, initial=initial)
    if form.is_valid():
        form.save()
        return redirect("list_sessions")

    context["title"] = "Add New Session"
    context["form"] = form
    return render(request, "add.html", context)


def update_session(request, session_id=None):
    session = Session.objects.get(id=session_id)
    session.finish_now()
    session.save()
    return redirect("list_sessions")


def start_session(request, purchase_id=None):
    session = SessionForm({"purchase": purchase_id, "timestamp_start": now_with_tz()})
    session.save()
    return redirect("list_sessions")


def delete_session(request, session_id=None):
    session = Session.objects.get(id=session_id)
    session.delete()
    return redirect("list_sessions")


def list_sessions(request, filter="", purchase_id="", platform_id="", game_id=""):
    context = {}

    if filter == "purchase":
        dataset = Session.objects.filter(purchase=purchase_id)
        context["purchase"] = Purchase.objects.get(id=purchase_id)
    elif filter == "platform":
        dataset = Session.objects.filter(purchase__platform=platform_id)
        context["platform"] = Platform.objects.get(id=platform_id)
    elif filter == "game":
        dataset = Session.objects.filter(purchase__game=game_id)
        context["game"] = Game.objects.get(id=game_id)
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


def add_platform(request):
    context = {}
    form = PlatformForm(request.POST or None)
    if form.is_valid():
        form.save()
        return redirect("index")

    context["form"] = form
    context["title"] = "Add New Platform"
    return render(request, "add.html", context)


def index(request):
    context = {}
    context["total_duration"] = Session().duration_sum
    context["title"] = "Index"
    return render(request, "index.html", context)
