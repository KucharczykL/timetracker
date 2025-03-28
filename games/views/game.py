from typing import Any

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Prefetch, Q
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse

from common.components import (
    A,
    Button,
    Div,
    Form,
    Icon,
    LinkedPurchase,
    NameWithIcon,
    Popover,
    PopoverTruncated,
    PurchasePrice,
)
from common.time import (
    dateformat,
    durationformat,
    durationformat_manual,
    format_duration,
    local_strftime,
    timeformat,
)
from common.utils import build_dynamic_filter, safe_division, truncate
from games.forms import GameForm
from games.models import Game, Purchase
from games.views.general import use_custom_redirect


@login_required
def list_games(request: HttpRequest, search_string: str = "") -> HttpResponse:
    context: dict[Any, Any] = {}
    page_number = request.GET.get("page", 1)
    limit = request.GET.get("limit", 10)
    games = Game.objects.order_by("-created_at")
    page_obj = None
    search_string = request.GET.get("search_string", search_string)
    if search_string != "":
        filters = [
            Q(name__icontains=search_string),
            Q(sort_name__icontains=search_string),
            Q(platform__name__icontains=search_string),
        ]
        try:
            year_value = int(search_string)
        except ValueError:
            year_value = None
        if year_value:
            filters.append(Q(year_released=year_value))
        search_string_parts = search_string.split()
        # only search for status if it exactly matches and is the only word
        if len(search_string_parts) == 1:
            if search_string.title() in Game.Status.labels:
                search_status = Game.Status[search_string.upper()]
                filters.append(Q(status=search_status))
        games = games.filter(build_dynamic_filter(filters, "|"))
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
            "header_action": Div(
                children=[
                    Form(
                        children=[
                            render_to_string(
                                "cotton/search_field.html",
                                {
                                    "id": "search_string",
                                    "search_string": search_string,
                                },
                            )
                        ]
                    ),
                    A([], Button([], "Add game"), url="add_game"),
                ],
                attributes=[("class", "flex justify-between")],
            ),
            "columns": [
                "Name",
                "Sort Name",
                "Year",
                "Status",
                "Wikidata",
                "Created",
                "Actions",
            ],
            "rows": [
                [
                    NameWithIcon(game_id=game.pk),
                    PopoverTruncated(
                        game.sort_name
                        if game.sort_name is not None and game.name != game.sort_name
                        else "(identical)"
                    ),
                    game.year_released,
                    render_to_string(
                        "cotton/gamestatus.html",
                        {"status": game.status, "slot": game.get_status_display()},
                    ),
                    game.wikidata,
                    local_strftime(game.created_at, dateformat),
                    render_to_string(
                        "cotton/button_group.html",
                        {
                            "buttons": [
                                {
                                    "href": reverse("edit_game", args=[game.pk]),
                                    "slot": Icon("edit"),
                                    "color": "gray",
                                },
                                {
                                    "href": reverse("delete_game", args=[game.pk]),
                                    "slot": Icon("delete"),
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
                reverse("add_purchase_for_game", kwargs={"game_id": game.id})
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
        "purchases",
        queryset=Purchase.objects.filter(type=Purchase.GAME).prefetch_related(
            nongame_related_purchases_prefetch
        ),
        to_attr="game_purchases",
    )

    purchases = game.purchases.order_by("date_purchased")

    sessions = game.sessions
    session_count = sessions.count()
    session_count_without_manual = game.sessions.without_manual().count()

    if sessions.exists():
        playrange_start = local_strftime(sessions.earliest().timestamp_start, "%b %Y")
        latest_session = sessions.latest()
        playrange_end = local_strftime(latest_session.timestamp_start, "%b %Y")

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

    purchase_data: dict[str, Any] = {
        "columns": ["Name", "Type", "Date", "Price", "Actions"],
        "rows": [
            [
                LinkedPurchase(purchase),
                purchase.get_type_display(),
                purchase.date_purchased.strftime(dateformat),
                PurchasePrice(purchase),
                render_to_string(
                    "cotton/button_group.html",
                    {
                        "buttons": [
                            {
                                "href": reverse("edit_purchase", args=[purchase.pk]),
                                "slot": Icon("edit"),
                                "color": "gray",
                            },
                            {
                                "href": reverse("delete_purchase", args=[purchase.pk]),
                                "slot": Icon("delete"),
                                "color": "red",
                            },
                        ]
                    },
                ),
            ]
            for purchase in purchases
        ],
    }

    sessions_all = game.sessions.order_by("-timestamp_start")

    last_session = None
    if sessions_all.exists():
        last_session = sessions_all.latest()
    session_count = sessions_all.count()
    session_paginator = Paginator(sessions_all, 5)
    page_number = request.GET.get("page", 1)
    session_page_obj = session_paginator.get_page(page_number)
    sessions = session_page_obj.object_list

    session_data: dict[str, Any] = {
        "header_action": Div(
            children=[
                A(
                    url="add_session",
                    children=Button(
                        icon=True,
                        size="xs",
                        children=[Icon("play"), "LOG"],
                    ),
                ),
                A(
                    url=reverse(
                        "list_sessions_start_session_from_session",
                        args=[last_session.pk],
                    ),
                    children=Popover(
                        popover_content=last_session.game.name,
                        children=[
                            Button(
                                icon=True,
                                color="gray",
                                size="xs",
                                children=[
                                    Icon("play"),
                                    truncate(f"{last_session.game.name}"),
                                ],
                            )
                        ],
                    ),
                )
                if last_session
                else "",
            ],
        ),
        "columns": ["Game", "Date", "Duration", "Actions"],
        "rows": [
            [
                NameWithIcon(
                    session_id=session.pk,
                ),
                f"{local_strftime(session.timestamp_start)}{f' — {local_strftime(session.timestamp_end, timeformat)}' if session.timestamp_end else ''}",
                (
                    format_duration(session.duration_calculated, durationformat)
                    if session.duration_calculated
                    else f"{format_duration(session.duration_manual, durationformat_manual)}*"
                ),
                render_to_string(
                    "cotton/button_group.html",
                    {
                        "buttons": [
                            {
                                "href": reverse(
                                    "list_sessions_end_session", args=[session.pk]
                                ),
                                "slot": Icon("end"),
                                "title": "Finish session now",
                                "color": "green",
                                "hover": "green",
                            }
                            if session.timestamp_end is None
                            # this only works without leaving an empty
                            # a element and wrong rounding of button edges
                            # because we check if button.href is not None
                            # in the button group component
                            else {},
                            {
                                "href": reverse("edit_session", args=[session.pk]),
                                "slot": Icon("edit"),
                                "color": "gray",
                            },
                            {
                                "href": reverse("delete_session", args=[session.pk]),
                                "slot": Icon("delete"),
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
        "game": game,
        "playrange": playrange,
        "purchase_count": game.purchases.count(),
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
