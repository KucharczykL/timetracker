from typing import Any

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.urls import reverse

from common.time import format_duration
from games.models import Session
from games.views import dateformat, datetimeformat, timeformat


@login_required
def list_sessions(request: HttpRequest) -> HttpResponse:
    context: dict[Any, Any] = {}
    page_number = request.GET.get("page", 1)
    limit = request.GET.get("limit", 10)
    sessions = Session.objects.order_by("-created_at")
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
                    session.purchase.edition.name,
                    f"{session.timestamp_start.strftime(datetimeformat)}{f" — {session.timestamp_end.strftime(timeformat)}" if session.timestamp_end else ""}",
                    (
                        format_duration(session.duration_calculated, "%2.1H hours")
                        if session.duration_calculated
                        else "-"
                    ),
                    (
                        format_duration(session.duration_manual)
                        if session.duration_manual
                        else "-"
                    ),
                    session.device,
                    session.created_at.strftime(dateformat),
                    render_to_string(
                        "components/button_group_sm.html",
                        {
                            "buttons": [
                                {
                                    "href": reverse("edit_session", args=[session.pk]),
                                    "text": "Edit",
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
