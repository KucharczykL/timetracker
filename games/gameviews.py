from typing import Any

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.urls import reverse

from games.models import Game
from games.views import dateformat


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
                    game.name,
                    game.sort_name,
                    game.year_released,
                    game.wikidata,
                    game.created_at.strftime(dateformat),
                    render_to_string(
                        "components/button_group_sm.html",
                        {
                            "buttons": [
                                {
                                    "href": reverse("edit_game", args=[game.pk]),
                                    "text": "Edit",
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
