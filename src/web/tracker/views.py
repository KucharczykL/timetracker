from django.shortcuts import render, redirect

from .models import Game, Platform, Purchase, Session
from .forms import SessionForm, PurchaseForm, GameForm, PlatformForm
from datetime import datetime
from zoneinfo import ZoneInfo
from django.conf import settings
from common.util.time import now as now_with_tz


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
    initial = {"timestamp_start": now}
    form = SessionForm(request.POST or None, initial=initial)
    if form.is_valid():
        form.save()
        return redirect("list_sessions")

    context["form"] = form
    return render(request, "add_session.html", context)


def update_session(request, session_id=None):
    session = Session.objects.get(id=session_id)
    session.finish_now()
    session.save()
    return redirect("list_sessions")


def delete_session(request, session_id=None):
    session = Session.objects.get(id=session_id)
    session.delete()
    return redirect("list_sessions")


def list_sessions(request, purchase_id=None):
    context = {}

    if purchase_id != None:
        dataset = Session.objects.filter(purchase=purchase_id)
        context["purchase"] = Purchase.objects.get(id=purchase_id)
    else:
        dataset = Session.objects.all()

    for session in dataset:
        if session.timestamp_end == None and session.duration_manual == None:
            session.timestamp_end = datetime.now(ZoneInfo(settings.TIME_ZONE))
            session.unfinished = True

    context["dataset"] = dataset

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
    return render(request, "index.html", context)
