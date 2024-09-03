from typing import Any

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Prefetch
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse

from common.time import format_duration
from common.utils import A, Button, safe_division, truncate_with_popover
from games.forms import GameForm
from games.models import Edition, Game, Purchase, Session
from games.views.general import (
    dateformat,
    datetimeformat,
    durationformat,
    durationformat_manual,
    timeformat,
    use_custom_redirect,
)


@login_required
def list_games(request: HttpRequest) -> HttpResponse:
    context: dict[Any, Any] = {}
    page_number = request.GET.get("page", 1)
    limit = request.GET.get("limit", 10)
    games = Game.objects.order_by("-created_at")
    page_obj = None
    if int(limit) != 0:
        paginator = Paginator(games, limit)
        page_obj = paginator.get_page(page_number)
        games = page_obj.object_list

    context = {
        "title": "Manage games",
        "page_obj": page_obj or None,
        "elided_page_range": (
            page_obj.paginator.get_elided_page_range(
                page_number, on_each_side=1, on_ends=1
            )
            if page_obj
            else None
        ),
        "data": {
            "header_action": A([], Button([], "Add game"), url="add_game"),
            "columns": [
                "Name",
                "Sort Name",
                "Year",
                "Wikidata",
                "Created",
                "Actions",
            ],
            "rows": [
                [
                    A(
                        [
                            (
                                "href",
                                reverse(
                                    "view_game",
                                    args=[game.pk],
                                ),
                            )
                        ],
                        truncate_with_popover(game.name),
                    ),
                    truncate_with_popover(
                        game.sort_name
                        if game.sort_name is not None and game.name != game.sort_name
                        else "(identical)"
                    ),
                    game.year_released,
                    game.wikidata,
                    game.created_at.strftime(dateformat),
                    render_to_string(
                        "cotton/button_group_sm.html",
                        {
                            "buttons": [
                                {
                                    "href": reverse("edit_game", args=[game.pk]),
                                    "text": "Edit",
                                    "color": "gray",
                                },
                                {
                                    "href": reverse("delete_game", args=[game.pk]),
                                    "text": "Delete",
                                    "color": "red",
                                },
                            ]
                        },
                    ),
                ]
                for game in games
            ],
        },
    }
    return render(request, "list_purchases.html", context)


@login_required
def add_game(request: HttpRequest) -> HttpResponse:
    context: dict[str, Any] = {}
    form = GameForm(request.POST or None)
    if form.is_valid():
        game = form.save()
        if "submit_and_redirect" in request.POST:
            return HttpResponseRedirect(
                reverse("add_edition_for_game", kwargs={"game_id": game.id})
            )
        else:
            return redirect("list_games")

    context["form"] = form
    context["title"] = "Add New Game"
    context["script_name"] = "add_game.js"
    return render(request, "add_game.html", context)


@login_required
def delete_game(request: HttpRequest, game_id: int) -> HttpResponse:
    game = get_object_or_404(Game, id=game_id)
    game.delete()
    return redirect("list_sessions")


@login_required
@use_custom_redirect
def edit_game(request: HttpRequest, game_id: int) -> HttpResponse:
    context = {}
    purchase = get_object_or_404(Game, id=game_id)
    form = GameForm(request.POST or None, instance=purchase)
    if form.is_valid():
        form.save()
        return redirect("list_sessions")
    context["title"] = "Edit Game"
    context["form"] = form
    return render(request, "add.html", context)


@login_required
def view_game(request: HttpRequest, game_id: int) -> HttpResponse:
    game = Game.objects.get(id=game_id)
    nongame_related_purchases_prefetch: Prefetch[Purchase] = Prefetch(
        "related_purchases",
        queryset=Purchase.objects.exclude(type=Purchase.GAME).order_by(
            "date_purchased"
        ),
        to_attr="nongame_related_purchases",
    )
    game_purchases_prefetch: Prefetch[Purchase] = Prefetch(
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

    purchases = Purchase.objects.filter(edition__game=game).order_by("date_purchased")

    sessions = Session.objects.prefetch_related("device").filter(
        purchase__edition__game=game
    )
    session_count = sessions.count()
    session_count_without_manual = (
        Session.objects.without_manual().filter(purchase__edition__game=game).count()
    )

    if sessions:
        playrange_start = sessions.earliest().timestamp_start.strftime("%b %Y")
        latest_session = sessions.latest()
        playrange_end = latest_session.timestamp_start.strftime("%b %Y")

        playrange = (
            playrange_start
            if playrange_start == playrange_end
            else f"{playrange_start} — {playrange_end}"
        )
    else:
        playrange = "N/A"
        latest_session = None

    total_hours = float(format_duration(sessions.total_duration_unformatted(), "%2.1H"))
    total_hours_without_manual = float(
        format_duration(sessions.calculated_duration_unformatted(), "%2.1H")
    )

    edition_data: dict[str, Any] = {
        "columns": [
            "Name",
            "Platform",
            "Year Released",
            "Actions",
        ],
        "rows": [
            [
                edition.name,
                edition.platform,
                edition.year_released,
                render_to_string(
                    "cotton/button_group_sm.html",
                    {
                        "buttons": [
                            {
                                "href": reverse("edit_edition", args=[edition.pk]),
                                "text": "Edit",
                                "color": "gray",
                            },
                            {
                                "href": reverse("delete_edition", args=[edition.pk]),
                                "text": "Delete",
                                "color": "red",
                            },
                        ]
                    },
                ),
            ]
            for edition in editions
        ],
    }

    purchase_data: dict[str, Any] = {
        "columns": ["Name", "Type", "Price", "Actions"],
        "rows": [
            [
                purchase.name if purchase.name else purchase.edition.name,
                purchase.get_type_display(),
                f"{purchase.price} {purchase.price_currency}",
                render_to_string(
                    "cotton/button_group_sm.html",
                    {
                        "buttons": [
                            {
                                "href": reverse("edit_purchase", args=[purchase.pk]),
                                "text": "Edit",
                                "color": "gray",
                            },
                            {
                                "href": reverse("delete_purchase", args=[purchase.pk]),
                                "text": "Delete",
                                "color": "red",
                            },
                        ]
                    },
                ),
            ]
            for purchase in purchases
        ],
    }

    sessions_all = Session.objects.filter(purchase__edition__game=game).order_by(
        "-timestamp_start"
    )
    session_count = sessions_all.count()
    session_paginator = Paginator(sessions_all, 5)
    page_number = request.GET.get("page", 1)
    session_page_obj = session_paginator.get_page(page_number)
    sessions = session_page_obj.object_list

    session_data: dict[str, Any] = {
        "columns": ["Date", "Duration", "Duration (manual)", "Actions"],
        "rows": [
            [
                f"{session.timestamp_start.strftime(datetimeformat)}{f" — {session.timestamp_end.strftime(timeformat)}" if session.timestamp_end else ""}",
                (
                    format_duration(session.duration_calculated, durationformat)
                    if session.duration_calculated
                    else "-"
                ),
                (
                    format_duration(session.duration_manual, durationformat_manual)
                    if session.duration_manual
                    else "-"
                ),
                render_to_string(
                    "cotton/button_group_sm.html",
                    {
                        "buttons": [
                            {
                                "href": reverse("edit_session", args=[session.pk]),
                                "text": "Edit",
                                "color": "gray",
                            },
                            {
                                "href": reverse("delete_session", args=[session.pk]),
                                "text": "Delete",
                                "color": "red",
                            },
                        ]
                    },
                ),
            ]
            for session in sessions
        ],
    }

    context: dict[str, Any] = {
        "edition_count": editions.count(),
        "editions": editions,
        "game": game,
        "playrange": playrange,
        "purchase_count": Purchase.objects.filter(edition__game=game).count(),
        "session_average_without_manual": round(
            safe_division(
                total_hours_without_manual, int(session_count_without_manual)
            ),
            1,
        ),
        "session_count": session_count,
        "sessions": sessions,
        "title": f"Game Overview - {game.name}",
        "hours_sum": total_hours,
        "edition_data": edition_data,
        "purchase_data": purchase_data,
        "session_data": session_data,
        "session_page_obj": session_page_obj,
        "session_elided_page_range": (
            session_page_obj.paginator.get_elided_page_range(
                page_number, on_each_side=1, on_ends=1
            )
            if session_page_obj and session_count > 5
            else None
        ),
    }

    request.session["return_path"] = request.path
    return render(request, "view_game.html", context)
