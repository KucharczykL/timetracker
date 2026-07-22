from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse

from common.components import (
    AddForm,
    ButtonGroup,
    Column,
    ContentContainer,
    Icon,
    QuickFilterBar,
    TableData,
    make_row,
    paginated_table_content,
    parse_filter_dict,
)
from common.layout import render_page
from common.time import dateformat, local_strftime
from common.utils import paginate
from games.sorting import (
    PLATFORM_DEFAULT_SORT,
    PLATFORM_SORTS,
    apply_sort,
    parse_find_filter,
)
from games.filters import parse_platform_filter
from games.forms import PlatformForm
from games.views.filtering import (
    apply_structured_filter,
    builder_url_for,
    warn_unknown_sort,
)
from games.models import Platform
from games.views.general import use_custom_redirect


@login_required
def list_platforms(request: HttpRequest) -> HttpResponse:
    platforms = Platform.objects.all()

    filter_json = request.GET.get("filter", "")
    if filter_json:
        platform_filter = apply_structured_filter(
            request, parse_platform_filter, filter_json
        )
        if platform_filter is not None:
            platforms = platforms.filter(platform_filter.to_q())

    find = parse_find_filter(request)
    sort = apply_sort(platforms, find, PLATFORM_SORTS, PLATFORM_DEFAULT_SORT)
    platforms = sort.queryset
    warn_unknown_sort(request, sort.unknown, entity="platform")
    platforms, page_obj, elided_page_range = paginate(platforms, find)

    data: TableData = {
        "columns": [
            Column("Name", "name"),
            Column("Icon"),
            Column("Group", "group"),
            Column("Created", "created"),
            Column("Actions", align="right"),
        ],
        "sort_terms": sort.terms,
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
        page_size=find.per_page,
    )
    # Thread the active sort + rows-per-page into the builder so a preset saved
    # there captures both (#335 sort, #337 per_page).
    builder_url = builder_url_for(
        "platforms", filter_json, find.sort, find.per_page_override
    )
    parsed_filter = parse_filter_dict(filter_json)
    quick_bar = QuickFilterBar(
        mode="platforms",
        existing=parsed_filter,
        preset_api_url=reverse("api-1.0.0:list_presets"),
        builder_url=builder_url,
        per_page_override=find.per_page_override,
    )
    content = ContentContainer()[quick_bar, content]
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
