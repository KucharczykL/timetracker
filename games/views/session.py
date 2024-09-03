from typing import Any

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from common.time import format_duration
from common.utils import A, Button, truncate_with_popover
from games.forms import SessionForm
from games.models import Purchase, Session
from games.views.general import (
    dateformat,
    datetimeformat,
    durationformat,
    durationformat_manual,
    timeformat,
    use_custom_redirect,
)


@login_required
def list_sessions(request: HttpRequest) -> HttpResponse:
    context: dict[Any, Any] = {}
    page_number = request.GET.get("page", 1)
    limit = request.GET.get("limit", 10)
    sessions = Session.objects.order_by("-timestamp_start")
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
            "header_action": A([], Button([], "Add session"), url="add_session"),
            "columns": [
                "Name",
                "Date",
                "Duration",
                "Duration (manual)",
                "Device",
                "Created",
                "Actions",
            ],
            "rows": [
                [
                    A(
                        children=truncate_with_popover(session.purchase.edition.name),
                        url=reverse(
                            "view_game",
                            args=[session.purchase.edition.game.pk],
                        ),
                    ),
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
                    session.device,
                    session.created_at.strftime(dateformat),
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
                                    "href": reverse(
                                        "delete_session", args=[session.pk]
                                    ),
                                    "text": "Delete",
                                    "color": "red",
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
def add_session(request: HttpRequest, purchase_id: int = 0) -> HttpResponse:
    context = {}
    initial: dict[str, Any] = {"timestamp_start": timezone.now()}

    last = Session.objects.last()
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
    return render(request, "add_session.html", context)


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
@use_custom_redirect
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
@use_custom_redirect
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
