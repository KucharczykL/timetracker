from common.time import format_duration, now as now_with_tz
from common.utils import safe_division
from datetime import datetime, timedelta
from django.conf import settings
from django.db.models import Sum, F, Count, Prefetch
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
    result = {
        "stats_dropdown_year_range": range(
            datetime.now(ZoneInfo(settings.TIME_ZONE)).year, 1999, -1
        )
    }
    return result


def add_session(request, purchase_id=None):
    context = {}
    initial = {"timestamp_start": now_with_tz()}

    last = Session.objects.all().last()
    if last != None:
        initial["purchase"] = last.purchase

    if request.method == "POST":
        form = SessionForm(request.POST or None, initial=initial)
        if form.is_valid():
            form.save()
            return redirect("list_sessions")
    else:
        if purchase_id:
            purchase = Purchase.objects.get(id=purchase_id)
            form = SessionForm(
                initial={
                    **initial,
                    "purchase": purchase,
                }
            )
        else:
            form = SessionForm(initial=initial)

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
    context["script_name"] = "add_purchase.js"
    return render(request, "add_purchase.html", context)


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
    game = Game.objects.get(id=game_id)
    nongame_related_purchases_prefetch = Prefetch(
        "related_purchases",
        queryset=Purchase.objects.exclude(type=Purchase.GAME),
        to_attr="nongame_related_purchases",
    )
    game_purchases_prefetch = Prefetch(
        "purchase_set",
        queryset=Purchase.objects.filter(type=Purchase.GAME).prefetch_related(
            nongame_related_purchases_prefetch
        ),
        to_attr="game_purchases",
    )
    editions = (
        Edition.objects.filter(game=game)
        .prefetch_related(game_purchases_prefetch)
        .order_by("year_released")
    )

    sessions = Session.objects.filter(purchase__edition__game=game).order_by(
        "timestamp_start"
    )
    session_count = sessions.count()

    playrange_start = sessions.first().timestamp_start.strftime("%b %Y")
    playrange_end = sessions.last().timestamp_start.strftime("%b %Y")

    playrange = (
        playrange_start
        if playrange_start == playrange_end
        else f"{playrange_start} — {playrange_end}"
    )
    total_hours = float(format_duration(sessions.total_duration_unformatted(), "%2.1H"))

    context = {
        "edition_count": editions.count(),
        "editions": editions,
        "game": game,
        "playrange": playrange,
        "purchase_count": Purchase.objects.filter(edition__game=game).count(),
        "session_average": round(total_hours / int(session_count), 1),
        "session_count": session_count,
        "sessions_with_notes": sessions.exclude(note=""),
        "sessions": sessions.order_by("-timestamp_start"),
        "title": f"Game Overview - {game.name}",
        "hours_sum": total_hours,
    }

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


def related_purchase_by_edition(request):
    edition_id = request.GET.get("edition")
    form = PurchaseForm()
    form.fields["related_purchase"].queryset = Purchase.objects.filter(
        edition_id=edition_id, type=Purchase.GAME
    ).order_by("edition__sort_name")
    return render(request, "partials/related_purchase_field.html", {"form": form})


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
    this_year_sessions = Session.objects.filter(timestamp_start__year=year)
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
    this_year_purchases_with_currency = this_year_purchases.filter(
        price_currency__exact=selected_currency
    )
    this_year_purchases_without_refunded = this_year_purchases_with_currency.filter(
        date_refunded=None
    )
    this_year_purchases_refunded = this_year_purchases_with_currency.refunded()

    this_year_purchases_unfinished = this_year_purchases_without_refunded.filter(
        date_finished__isnull=True
    ).filter(
        type=Purchase.GAME
    )  # do not count DLC etc.

    this_year_purchases_unfinished_percent = int(
        safe_division(
            this_year_purchases_unfinished.count(), this_year_purchases_refunded.count()
        )
        * 100
    )

    purchases_finished_this_year = Purchase.objects.filter(date_finished__year=year)
    purchases_finished_this_year_released_this_year = (
        purchases_finished_this_year.filter(edition__year_released=year).order_by(
            "date_finished"
        )
    )
    purchased_this_year_finished_this_year = (
        this_year_purchases_without_refunded.intersection(
            purchases_finished_this_year
        ).order_by("date_finished")
    )

    this_year_spendings = this_year_purchases_without_refunded.aggregate(
        total_spent=Sum(F("price"))
    )
    total_spent = this_year_spendings["total_spent"] or 0

    games_with_playtime = (
        Game.objects.filter(edition__purchase__session__in=this_year_sessions)
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

    context = {
        "total_hours": format_duration(
            this_year_sessions.total_duration_unformatted(), "%2.0H"
        ),
        "total_games": this_year_played_purchases.count(),
        "total_2023_games": this_year_played_purchases.filter(
            edition__year_released=year
        ).count(),
        "top_10_games_by_playtime": top_10_games_by_playtime,
        "year": year,
        "total_playtime_per_platform": total_playtime_per_platform,
        "total_spent": total_spent,
        "total_spent_currency": selected_currency,
        "all_purchased_this_year": this_year_purchases_without_refunded,
        "spent_per_game": int(
            safe_division(total_spent, this_year_purchases_without_refunded.count())
        ),
        "all_finished_this_year": purchases_finished_this_year.order_by(
            "date_finished"
        ),
        "this_year_finished_this_year": purchases_finished_this_year_released_this_year.order_by(
            "date_finished"
        ),
        "purchased_this_year_finished_this_year": purchased_this_year_finished_this_year.order_by(
            "date_finished"
        ),
        "total_sessions": this_year_sessions.count(),
        "unique_days": unique_days["dates"],
        "unique_days_percent": int(unique_days["dates"] / 365 * 100),
        "purchased_unfinished": this_year_purchases_unfinished,
        "unfinished_purchases_percent": this_year_purchases_unfinished_percent,
        "refunded_percent": int(
            safe_division(
                this_year_purchases_refunded.count(),
                this_year_purchases_with_currency.count(),
            )
            * 100
        ),
        "all_purchased_refunded_this_year": this_year_purchases_refunded,
        "all_purchased_this_year": this_year_purchases_with_currency.order_by(
            "date_purchased"
        ),
        "backlog_decrease_count": backlog_decrease_count,
    }

    request.session["return_path"] = request.path
    return render(request, "stats.html", context)


def add_purchase(request, edition_id=None):
    context = {}
    initial = {"date_purchased": now_with_tz()}

    if request.method == "POST":
        form = PurchaseForm(request.POST or None, initial=initial)
        if form.is_valid():
            purchase = form.save()
            if "submit_and_redirect" in request.POST:
                return HttpResponseRedirect(
                    reverse(
                        "add_session_for_purchase", kwargs={"purchase_id": purchase.id}
                    )
                )
            else:
                return redirect("index")
    else:
        if edition_id:
            edition = Edition.objects.get(id=edition_id)
            form = PurchaseForm(
                initial={
                    **initial,
                    "edition": edition,
                    "platform": edition.platform,
                }
            )
        else:
            form = PurchaseForm(initial=initial)

    context["form"] = form
    context["title"] = "Add New Purchase"
    context["script_name"] = "add_purchase.js"
    return render(request, "add_purchase.html", context)


def add_game(request):
    context = {}
    form = GameForm(request.POST or None)
    if form.is_valid():
        game = form.save()
        if "submit_and_redirect" in request.POST:
            return HttpResponseRedirect(
                reverse("add_edition_for_game", kwargs={"game_id": game.id})
            )
        else:
            return redirect("index")

    context["form"] = form
    context["title"] = "Add New Game"
    context["script_name"] = "add_game.js"
    return render(request, "add_game.html", context)


def add_edition(request, game_id=None):
    context = {}
    if request.method == "POST":
        form = EditionForm(request.POST or None)
        if form.is_valid():
            edition = form.save()
            if "submit_and_redirect" in request.POST:
                return HttpResponseRedirect(
                    reverse(
                        "add_purchase_for_edition", kwargs={"edition_id": edition.id}
                    )
                )
            else:
                return redirect("index")
    else:
        if game_id:
            game = Game.objects.get(id=game_id)
            form = EditionForm(
                initial={
                    "game": game,
                    "name": game.name,
                    "sort_name": game.sort_name,
                    "year_released": game.year_released,
                }
            )
        else:
            form = EditionForm()

    context["form"] = form
    context["title"] = "Add New Edition"
    context["script_name"] = "add_edition.js"
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
