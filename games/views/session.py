from typing import Any

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from common.components import (
    A,
    Button,
    Div,
    Form,
    Icon,
    NameWithIcon,
    Popover,
)
from common.time import (
    dateformat,
    durationformat,
    durationformat_manual,
    format_duration,
    local_strftime,
    timeformat,
)
from common.utils import truncate
from games.forms import SessionForm
from games.models import Game, Session
from games.views.general import use_custom_redirect


@login_required
def list_sessions(request: HttpRequest, search_string: str = "") -> HttpResponse:
    context: dict[Any, Any] = {}
    page_number = request.GET.get("page", 1)
    limit = request.GET.get("limit", 10)
    sessions = Session.objects.order_by("-timestamp_start", "created_at")
    search_string = request.GET.get("search_string", search_string)
    if search_string != "":
        sessions = sessions.filter(
            Q(game__name__icontains=search_string)
            | Q(game__name__icontains=search_string)
            | Q(game__platform__name__icontains=search_string)
            | Q(device__name__icontains=search_string)
            | Q(device__type__icontains=search_string)
        )
    try:
        last_session = sessions.latest()
    except Session.DoesNotExist:
        last_session = None
    page_obj = None
    if int(limit) != 0:
        paginator = Paginator(sessions, limit)
        page_obj = paginator.get_page(page_number)
        sessions = page_obj.object_list

    context = {
        "title": "Manage sessions",
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
                    Div(
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
                        ]
                    ),
                ],
                attributes=[("class", "flex justify-between")],
            ),
            "columns": [
                "Name",
                "Date",
                "Duration",
                "Device",
                "Created",
                "Actions",
            ],
            "rows": [
                [
                    NameWithIcon(session_id=session.pk),
                    f"{local_strftime(session.timestamp_start)}{f' — {local_strftime(session.timestamp_end, timeformat)}' if session.timestamp_end else ''}",
                    (
                        format_duration(session.duration_calculated, durationformat)
                        if session.duration_calculated
                        else f"{format_duration(session.duration_manual, durationformat_manual)}*"
                    ),
                    session.device,
                    session.created_at.strftime(dateformat),
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
                                    "title": "Edit",
                                    # "color": "gray",
                                    "hover": "green",
                                },
                                {
                                    "href": reverse(
                                        "delete_session", args=[session.pk]
                                    ),
                                    "slot": Icon("delete"),
                                    "title": "Delete",
                                    "color": "red",
                                    "hover": "red",
                                },
                            ]
                        },
                    ),
                ]
                for session in sessions
            ],
        },
    }
    return render(request, "list_purchases.html", context)


@login_required
def search_sessions(request: HttpRequest) -> HttpResponse:
    return list_sessions(request, search_string=request.GET.get("search_string", ""))


@login_required
def add_session(request: HttpRequest, game_id: int = 0) -> HttpResponse:
    context = {}
    initial: dict[str, Any] = {"timestamp_start": timezone.now()}

    last = Session.objects.last()
    if last != None:
        initial["game"] = last.game

    if request.method == "POST":
        form = SessionForm(request.POST or None, initial=initial)
        if form.is_valid():
            form.save()
            return redirect("list_sessions")
    else:
        if game_id:
            game = Game.objects.get(id=game_id)
            form = SessionForm(
                initial={
                    **initial,
                    "game": game,
                }
            )
        else:
            form = SessionForm(initial=initial)

    context["title"] = "Add New Session"
    # TODO: re-add custom buttons #91
    # context["script_name"] = "add_session.js"
    context["form"] = form
    return render(request, "add.html", context)


@login_required
@use_custom_redirect
def edit_session(request: HttpRequest, session_id: int) -> HttpResponse:
    context = {}
    session = get_object_or_404(Session, id=session_id)
    form = SessionForm(request.POST or None, instance=session)
    if form.is_valid():
        form.save()
        return redirect("list_sessions")
    context["title"] = "Edit Session"
    context["form"] = form
    return render(request, "add.html", context)


def clone_session_by_id(session_id: int) -> Session:
    session = get_object_or_404(Session, id=session_id)
    clone = session
    clone.pk = None
    clone.timestamp_start = timezone.now()
    clone.timestamp_end = None
    clone.note = ""
    clone.save()
    return clone


@login_required
def new_session_from_existing_session(
    request: HttpRequest, session_id: int, template: str = ""
) -> HttpResponse:
    session = clone_session_by_id(session_id)
    if request.htmx:
        context = {
            "session": session,
            "session_count": int(request.GET.get("session_count", 0)) + 1,
        }
        return render(request, template, context)
    return redirect("list_sessions")


@login_required
def end_session(
    request: HttpRequest, session_id: int, template: str = ""
) -> HttpResponse:
    session = get_object_or_404(Session, id=session_id)
    session.timestamp_end = timezone.now()
    session.save()
    if request.htmx:
        context = {
            "session": session,
            "session_count": request.GET.get("session_count", 0),
        }
        return render(request, template, context)
    return redirect("list_sessions")


@login_required
def delete_session(request: HttpRequest, session_id: int = 0) -> HttpResponse:
    session = get_object_or_404(Session, id=session_id)
    session.delete()
    return redirect("list_sessions")


@login_required
def delete_session(request: HttpRequest, session_id: int = 0) -> HttpResponse:
    session = get_object_or_404(Session, id=session_id)
    session.delete()
    return redirect("list_sessions")
