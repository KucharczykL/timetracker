from typing import Any

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse

from common.components import A, Button, Icon
from common.time import dateformat, local_strftime
from games.forms import PlatformForm
from games.models import Platform
from games.views.general import use_custom_redirect


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
            "header_action": A([], Button([], "Add platform"), url="add_platform"),
            "columns": [
                "Name",
                "Icon",
                "Group",
                "Created",
                "Actions",
            ],
            "rows": [
                [
                    platform.name,
                    Icon(platform.icon),
                    platform.group,
                    local_strftime(platform.created_at, dateformat),
                    render_to_string(
                        "cotton/button_group.html",
                        {
                            "buttons": [
                                {
                                    "href": reverse(
                                        "edit_platform", args=[platform.pk]
                                    ),
                                    "slot": Icon("edit"),
                                    "color": "gray",
                                },
                                {
                                    "href": reverse(
                                        "delete_platform", args=[platform.pk]
                                    ),
                                    "slot": Icon("delete"),
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


@login_required
@use_custom_redirect
def edit_platform(request: HttpRequest, platform_id: int) -> HttpResponse:
    context = {}
    platform = get_object_or_404(Platform, id=platform_id)
    form = PlatformForm(request.POST or None, instance=platform)
    if form.is_valid():
        form.save()
        return redirect("list_platforms")
    context["title"] = "Edit Platform"
    context["form"] = form
    return render(request, "add.html", context)


@login_required
def add_platform(request: HttpRequest) -> HttpResponse:
    context: dict[str, Any] = {}
    form = PlatformForm(request.POST or None)
    if form.is_valid():
        form.save()
        return redirect("index")

    context["form"] = form
    context["title"] = "Add New Platform"
    return render(request, "add.html", context)
