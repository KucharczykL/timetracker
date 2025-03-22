import logging
from typing import Any, Callable, TypedDict

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import QuerySet
from django.db.models.manager import BaseManager
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.urls import reverse

from common.components import A, Button, Icon
from common.time import dateformat, local_strftime
from games.forms import PlayEventForm
from games.models import Game, PlayEvent

logger = logging.getLogger("games")


class TableData(TypedDict):
    header_action: Callable[..., Any]
    columns: list[str]
    rows: list[list[Any]]


def create_playevent_tabledata(
    playevents: list[PlayEvent] | BaseManager[PlayEvent] | QuerySet[PlayEvent],
    exclude_columns: list[str] = [],
    request: HttpRequest | None = None,
) -> TableData:
    column_list = [
        "Game",
        "Started",
        "Ended",
        "Days to finish",
        "Note",
        "Created",
        "Actions",
    ]
    filtered_column_list = filter(
        lambda x: x not in exclude_columns,
        column_list,
    )
    excluded_column_indexes = [column_list.index(column) for column in exclude_columns]

    row_list = [
        [
            playevent.game,
            playevent.started.strftime(dateformat) if playevent.started else "-",
            playevent.ended.strftime(dateformat) if playevent.ended else "-",
            playevent.days_to_finish if playevent.days_to_finish else "-",
            playevent.note,
            local_strftime(playevent.created_at, dateformat),
            render_to_string(
                "cotton/button_group.html",
                {
                    "buttons": [
                        {
                            "href": reverse("edit_playevent", args=[playevent.pk]),
                            "slot": Icon("edit"),
                            "color": "gray",
                        },
                        {
                            "href": reverse("delete_playevent", args=[playevent.pk]),
                            "slot": Icon("delete"),
                            "color": "red",
                        },
                    ]
                },
            ),
        ]
        for playevent in playevents
    ]
    filtered_row_list = [
        [column for idx, column in enumerate(row) if idx not in excluded_column_indexes]
        for row in row_list
    ]
    return {
        "header_action": A([], Button([], "Add play event"), url="add_playevent"),
        "columns": list(filtered_column_list),
        "rows": filtered_row_list,
    }


@login_required
def list_playevents(request: HttpRequest) -> HttpResponse:
    page_number = request.GET.get("page", 1)
    limit = request.GET.get("limit", 10)
    playevents = PlayEvent.objects.order_by("-created_at")
    page_obj = None
    if int(limit) != 0:
        paginator = Paginator(playevents, limit)
        page_obj = paginator.get_page(page_number)
        playevents = page_obj.object_list
    context: dict[str, Any] = {
        "title": "Manage play events",
        "page_obj": page_obj or None,
        "elided_page_range": (
            page_obj.paginator.get_elided_page_range(
                page_number, on_each_side=1, on_ends=1
            )
            if page_obj
            else None
        ),
        "data": create_playevent_tabledata(playevents, request=request),
    }
    return render(request, "list_playevents.html", context)


@login_required
def add_playevent(request: HttpRequest, game_id: int = 0) -> HttpResponse:
    initial: dict[str, Any] = {}
    if game_id:
        # coming from add_playevent_for_game url path
        game = get_object_or_404(Game, id=game_id)
        initial["game"] = game
    form = PlayEventForm(request.POST or None, initial=initial)
    if form.is_valid():
        form.save()
        if not game_id:
            # coming from add_playevent url path
            game_id = form.instance.game.id
        return HttpResponseRedirect(reverse("view_game", args=[game_id]))

    return render(request, "add.html", {"form": form, "title": "Add new playthrough"})


def edit_playevent(request: HttpRequest, playevent_id: int) -> HttpResponse:
    context: dict[str, Any] = {}
    playevent = get_object_or_404(PlayEvent, id=playevent_id)
    form = PlayEventForm(request.POST or None, instance=playevent)
    if form.is_valid():
        form.save()
        return HttpResponseRedirect(reverse("view_game", args=[playevent.game.id]))

    context = {
        "form": form,
        "title": "Edit Play Event",
    }
    return render(request, "add.html", context)


def delete_playevent(request: HttpRequest, playevent_id: int) -> HttpResponse:
    playevent = get_object_or_404(PlayEvent, id=playevent_id)
    playevent.delete()
    return HttpResponseRedirect(request.META.get("HTTP_REFERER", "/"))
