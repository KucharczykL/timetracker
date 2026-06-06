from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse

from common.components import (
    A,
    AddForm,
    Button,
    ButtonGroup,
    Icon,
    paginated_table_content,
)
from common.layout import render_page
from common.time import dateformat, local_strftime
from games.forms import PlatformForm
from games.models import Platform
from games.views.general import use_custom_redirect


@login_required
def list_platforms(request: HttpRequest) -> HttpResponse:
    page_number = request.GET.get("page", 1)
    limit = request.GET.get("limit", 10)
    platforms = Platform.objects.order_by("name")
    page_obj = None
    if int(limit) != 0:
        paginator = Paginator(platforms, limit)
        page_obj = paginator.get_page(page_number)
        platforms = page_obj.object_list
    elided_page_range = (
        page_obj.paginator.get_elided_page_range(page_number, on_each_side=1, on_ends=1)
        if page_obj
        else None
    )

    data = {
        "header_action": A(
            [], Button([], "Add platform"), url_name="games:add_platform"
        ),
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
                ButtonGroup(
                    [
                        {
                            "href": reverse("games:edit_platform", args=[platform.pk]),
                            "slot": Icon("edit"),
                            "color": "gray",
                        },
                        {
                            "href": reverse(
                                "games:delete_platform", args=[platform.pk]
                            ),
                            "slot": Icon("delete"),
                            "color": "red",
                        },
                    ]
                ),
            ]
            for platform in platforms
        ],
    }
    content = paginated_table_content(
        data,
        page_obj=page_obj,
        elided_page_range=elided_page_range,
        request=request,
    )
    return render_page(request, content, title="Manage platforms")


@login_required
def delete_platform(request: HttpRequest, platform_id: int) -> HttpResponse:
    platform = get_object_or_404(Platform, id=platform_id)
    platform.delete()
    return redirect("games:list_platforms")


@login_required
@use_custom_redirect
def edit_platform(request: HttpRequest, platform_id: int) -> HttpResponse:
    platform = get_object_or_404(Platform, id=platform_id)
    form = PlatformForm(request.POST or None, instance=platform)
    if form.is_valid():
        form.save()
        return redirect("games:list_platforms")
    return render_page(request, AddForm(form, request=request), title="Edit Platform")


@login_required
def add_platform(request: HttpRequest) -> HttpResponse:
    form = PlatformForm(request.POST or None)
    if form.is_valid():
        form.save()
        return redirect("games:index")

    return render_page(
        request, AddForm(form, request=request), title="Add New Platform"
    )
