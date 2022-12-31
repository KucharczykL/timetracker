from django.shortcuts import render

from .models import Game, Platform, Purchase, Session
from .forms import SessionForm, PurchaseForm, GameForm
from datetime import datetime
from django.db.models import ExpressionWrapper, F, DurationField


def add_session(request):
    context = {}
    now = datetime.now()
    initial = {"timestamp_start": now, "timestamp_end": now}
    form = SessionForm(request.POST or None, initial=initial)
    if form.is_valid():
        form.save()

    context["form"] = form
    return render(request, "add_session.html", context)


def list_sessions(request):
    context = {}
    dataset = Session.objects.annotate(
        time_delta=ExpressionWrapper(
            F("timestamp_end") - F("timestamp_start"), output_field=DurationField()
        )
    )
    context["dataset"] = dataset

    return render(request, "list_sessions.html", context)


def add_purchase(request):
    context = {}
    now = datetime.now()
    initial = {"date_purchased": now}
    form = PurchaseForm(request.POST or None, initial=initial)
    if form.is_valid():
        form.save()

    context["form"] = form
    return render(request, "add_purchase.html", context)


def add_game(request):
    context = {}
    form = GameForm(request.POST or None)
    if form.is_valid():
        form.save()

    context["form"] = form
    context["title"] = "Add New Game"
    return render(request, "add.html", context)
