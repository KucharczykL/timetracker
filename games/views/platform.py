from typing import cast

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse

from common.components import (
    AddForm,
    ButtonGroup,
    Column,
    ContentContainer,
    Icon,
    Li,
    QuickFilterBar,
    TableData,
    TruncatedText,
    Ul,
    make_row,
    paginated_table_content,
    parse_filter_dict,
)
from common.date_time_presentation import date_time_presentation_for_request
from common.filter_execution import regex_timeout_view
from common.layout import render_page
from common.returns import action_url
from common.utils import paginate
from games.filters import parse_platform_filter
from games.forms import PlatformForm
from games.models import Platform
from games.ownership import owned_or_404
from games.sorting import (
    PLATFORM_DEFAULT_SORT,
    PLATFORM_SORTS,
    apply_sort,
    parse_find_filter,
)
from games.views.deletion import confirm_and_delete
from games.views.filtering import (
    apply_structured_filter,
    builder_url_for,
    warn_unknown_sort,
)
from games.views.returns import return_url


@login_required
@regex_timeout_view
def list_platforms(request: HttpRequest) -> HttpResponse:
    library = cast(User, request.user).library
    presentation = date_time_presentation_for_request(request)
    origin = request.get_full_path()
    platforms = Platform.objects.for_library(library)

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
        "caption": "Platforms",
        "columns": [
            Column("Name", "name"),
            Column("Icon", priority=2),
            Column("Group", "group", priority=2),
            Column("Created", "created"),
            Column("Actions", align="right", priority=3),
        ],
        "sort_terms": sort.terms,
        "rows": [
            make_row(
                TruncatedText(platform.name),
                Icon(platform.icon),
                platform.group,
                presentation.format(platform.created_at, "date"),
                ButtonGroup(
                    [
                        {
                            "href": action_url(
                                "games:edit_platform", platform.pk, origin=origin
                            ),
                            "slot": Icon("edit"),
                            "color": "gray",
                        },
                        {
                            "href": action_url(
                                "games:delete_platform", platform.pk, origin=origin
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
    builder_url = builder_url_for(
        "platforms", filter_json, find.sort, find.per_page_override
    )
    parsed_filter = parse_filter_dict(filter_json)
    quick_bar = QuickFilterBar(
        presentation=presentation,
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
    library = cast(User, request.user).library
    platform = owned_or_404(
        Platform.objects.for_library(library), library, id=platform_id
    )
    return confirm_and_delete(
        request,
        platform,
        title="Delete platform",
        message=f"Permanently delete {platform.name}?",
        details=Ul()[
            Li()[
                f"{platform.game_set.count()} game(s) and "
                f"{platform.purchase_set.count()} purchase(s) become platformless"
            ]
        ],
        fallback="games:list_platforms",
    )


@login_required
def edit_platform(request: HttpRequest, platform_id: int) -> HttpResponse:
    library = cast(User, request.user).library
    platform = owned_or_404(
        Platform.objects.for_library(library), library, id=platform_id
    )
    form = PlatformForm(request.POST or None, instance=platform, library=library)
    if form.is_valid():
        form.save()
        return redirect(return_url(request, fallback="games:list_platforms"))
    return render_page(request, AddForm(form, request=request), title="Edit Platform")


@login_required
def add_platform(request: HttpRequest) -> HttpResponse:
    library = cast(User, request.user).library
    form = PlatformForm(request.POST or None, library=library)
    if form.is_valid():
        form.save()
        return redirect(return_url(request, fallback="games:list_platforms"))

    return render_page(
        request, AddForm(form, request=request), title="Add New Platform"
    )
