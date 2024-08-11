from typing import Any

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse

from games.models import Platform
from games.views import dateformat


@login_required
def list_platforms(request: HttpRequest) -> HttpResponse:
    context: dict[Any, Any] = {}
    page_number = request.GET.get("page", 1)
    limit = request.GET.get("limit", 10)
    platforms = Platform.objects.order_by("-created_at")
    page_obj = None
    if int(limit) != 0:
        paginator = Paginator(platforms, limit)
        page_obj = paginator.get_page(page_number)
        platforms = page_obj.object_list

    context = {
        "title": "Manage platforms",
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
                "Group",
                "Created",
                "Actions",
            ],
            "rows": [
                [
                    platform.name,
                    platform.group,
                    platform.created_at.strftime(dateformat),
                    render_to_string(
                        "components/button_group_sm.html",
                        {
                            "buttons": [
                                {
                                    "href": reverse(
                                        "edit_platform", args=[platform.pk]
                                    ),
                                    "text": "Edit",
                                },
                                {
                                    "href": reverse(
                                        "delete_platform", args=[platform.pk]
                                    ),
                                    "text": "Delete",
                                    "color": "red",
                                },
                            ]
                        },
                    ),
                ]
                for platform in platforms
            ],
        },
    }
    return render(request, "list_purchases.html", context)


@login_required
def delete_platform(request: HttpRequest, platform_id: int) -> HttpResponse:
    platform = get_object_or_404(Platform, id=platform_id)
    platform.delete()
    return redirect("list_platforms")
