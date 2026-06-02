import logging
from datetime import datetime, timedelta
from typing import Any, Callable, TypedDict

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import QuerySet
from django.db.models.manager import BaseManager
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from common.components import A, Button, ButtonGroup, Icon
from common.time import dateformat, format_duration, local_strftime
from games.forms import PlayEventForm
from games.models import Game, PlayEvent, Session

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
            ButtonGroup(
                [
                    {
                        "href": reverse("games:edit_playevent", args=[playevent.pk]),
                        "slot": Icon("edit"),
                        "color": "gray",
                    },
                    {
                        "href": reverse("games:delete_playevent", args=[playevent.pk]),
                        "slot": Icon("delete"),
                        "color": "red",
                    },
                ]
            ),
        ]
        for playevent in playevents
    ]
    filtered_row_list = [
        [column for idx, column in enumerate(row) if idx not in excluded_column_indexes]
        for row in row_list
    ]
    return {
         "header_action": A([], Button([], "Add play event"), url_name="games:add_playevent"),
        "columns": list(filtered_column_list),
        "rows": filtered_row_list,
    }


def _get_formatted_playtime_for_game_sessions_in_range(
    game: Game,
    start_timestamp: datetime | None = None,
    end_timestamp: datetime | None = None,
) -> str:
    """
    Calculates and formats the total playtime for a game's sessions
    between specified start and end timestamps. If timestamps are not provided,
    it uses the earliest and latest session start times for the game.
    Returns "0h 00m" if no sessions exist for the game or if the range is invalid.
    """
    sessions_queryset = game.sessions.all()

    if not sessions_queryset.exists():
        return "0h 00m"

    actual_start_ts = (
        start_timestamp
        if start_timestamp is not None
        else sessions_queryset.earliest("timestamp_start").timestamp_start
    )
    actual_end_ts = (
        end_timestamp
        if end_timestamp is not None
        else sessions_queryset.latest("timestamp_start").timestamp_start
    )

    sessions_in_range = sessions_queryset.filter(
        timestamp_start__gte=actual_start_ts, timestamp_start__lte=actual_end_ts
    )
    return format_duration(sessions_in_range.total_duration_unformatted(), "%Hh %mm")


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
        try:
            # First, try to get the latest session. If no sessions, then no playtime.
            latest_session = game.sessions.latest("timestamp_start")
            latest_session_ts = latest_session.timestamp_start

            # Now, determine the start date for the new playevent.
            # This will be either the day after the last playevent ended, or the earliest session.
            try:
                latest_playevent = game.playevents.latest("ended")
                # Start date for the new PlayEvent form
                new_playevent_form_start_date = latest_playevent.ended + timedelta(
                    days=1
                )
                initial["started"] = new_playevent_form_start_date

                # Start timestamp for playtime calculation
                playtime_calc_start_ts = datetime.combine(
                    new_playevent_form_start_date, datetime.min.time()
                )

            except PlayEvent.DoesNotExist:
                # No previous playevents, so the new playevent starts from the earliest session.
                earliest_session_ts = game.sessions.earliest(
                    "timestamp_start"
                ).timestamp_start
                initial["started"] = earliest_session_ts.date()
                playtime_calc_start_ts = earliest_session_ts

            # The end date for the new PlayEvent form and playtime calculation is the latest session's start date.
            initial["ended"] = latest_session_ts.date()
            playtime_calc_end_ts = latest_session_ts

            initial["note"] = _get_formatted_playtime_for_game_sessions_in_range(
                game, playtime_calc_start_ts, playtime_calc_end_ts
            )
        except Session.DoesNotExist:
            initial["started"] = None
            initial["ended"] = None
            initial["note"] = "0h 00m"
    form = PlayEventForm(request.POST or None, initial=initial)
    if form.is_valid():
        form.save()
        if not game_id:
            # coming from add_playevent url path
            game_id = form.instance.game.id
        return HttpResponseRedirect(reverse("games:view_game", args=[game_id]))

    return render(request, "add.html", {"form": form, "title": "Add new playthrough"})


def edit_playevent(request: HttpRequest, playevent_id: int) -> HttpResponse:
    context: dict[str, Any] = {}
    playevent = get_object_or_404(PlayEvent, id=playevent_id)
    form = PlayEventForm(request.POST or None, instance=playevent)
    if form.is_valid():
        form.save()
        return HttpResponseRedirect(reverse("games:view_game", args=[playevent.game.id]))

    context = {
        "form": form,
        "title": "Edit Play Event",
    }
    return render(request, "add.html", context)


def delete_playevent(request: HttpRequest, playevent_id: int) -> HttpResponse:
    playevent = get_object_or_404(PlayEvent, id=playevent_id)
    playevent.delete()
    return HttpResponseRedirect(request.META.get("HTTP_REFERER", "/"))
