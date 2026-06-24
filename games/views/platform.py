from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse

from common.components import (
    A,
    AddForm,
    ButtonGroup,
    Column,
    Fragment,
    Icon,
    PlatformFilterBar,
    StyledButton,
    TableData,
    make_row,
    paginated_table_content,
)
from common.layout import render_page
from common.time import dateformat, local_strftime
from common.utils import paginate
from games.filters import parse_platform_filter
from games.forms import PlatformForm
from games.models import Platform
from games.views.general import use_custom_redirect


@login_required
def list_platforms(request: HttpRequest) -> HttpResponse:
    platforms = Platform.objects.order_by("name")

    filter_json = request.GET.get("filter", "")
    if filter_json:
        platform_filter = parse_platform_filter(filter_json)
        if platform_filter is not None:
            platforms = platforms.filter(platform_filter.to_q())

    platforms, page_obj, elided_page_range = paginate(request, platforms)

    data: TableData = {
        "header_action": A(href=reverse("games:add_platform"))[
            StyledButton()["Add platform"]
        ],
        "columns": [
            Column("Name"),
            Column("Icon"),
            Column("Group"),
            Column("Created"),
            Column("Actions", align="right"),
        ],
        "rows": [
            make_row(
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
            )
            for platform in platforms
        ],
    }
    content = paginated_table_content(
        data,
        page_obj=page_obj,
        elided_page_range=elided_page_range,
        request=request,
    )
    filter_bar = PlatformFilterBar(
        filter_json=filter_json,
        preset_list_url=reverse("games:list_presets") + "?mode=platforms",
        preset_save_url=reverse("games:save_preset") + "?mode=platforms",
    )
    content = Fragment(filter_bar, content)
    return render_page(
        request,
        content,
        title="Manage platforms",
    )


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
