from functools import partial
from typing import cast
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import HttpRequest, HttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from common.components import (
    AddForm,
    Column,
    ContentContainer,
    ExternalReferenceLinks,
    FormFields,
    Fragment,
    Icon,
    Li,
    QuickFilterBar,
    TableData,
    TruncatedText,
    Ul,
    drop_columns,
    make_row,
    paginated_table_content,
    parse_filter_dict,
)
from common.components.core import Node
from common.date_time_presentation import date_time_presentation_for_request
from common.filter_execution import execute_filter, regex_timeout_view
from common.form_dialog import CreatedRedirect
from common.layout import render_page
from common.utils import paginate
from games.bulk_platform_edit import EDIT_PLATFORMS
from games.bulk_removal import REMOVE_PLATFORM
from games.bulk_tray import tray_actions
from games.filters import (
    PlatformFilter,
    filter_query_context_for_library,
    parse_platform_filter,
)
from games.forms import PlatformForm, platform_option
from games.list_columns import column_choice
from games.models import Platform, UserLibrary
from games.ownership import owned_or_404
from games.reads.external_references import held_by, references_for
from games.reads.platform_departures import platform_departures
from games.reference_form import ReferenceSetForm, submitted_or_form_error
from games.sorting import (
    PLATFORM_DEFAULT_SORT,
    PLATFORM_SORTS,
    apply_sort,
    parse_find_filter,
)
from games.views.filtering import (
    apply_structured_filter,
    builder_url_for,
    warn_unknown_sort,
)
from games.views.platform_menu import platform_row_menu
from games.views.reference_section import references_area
from games.views.removal import confirm_and_remove, restore_and_return
from games.views.returns import return_url
from games.writes.platform import restore_platform_by_hand

PLATFORM_COLUMNS: list[Column] = [
    Column("Name", "name", key="name", hideable=False),
    Column("Icon", priority=2, key="icon"),
    Column("Group", "group", priority=2, key="group"),
    Column("References", priority=2, key="references", hidden_by_default=True),
    Column("Created", "created", key="created", hidden_by_default=True),
]


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
            platforms = execute_filter(
                platform_filter,
                platforms,
                filter_query_context_for_library(library),
            )

    find = parse_find_filter(request)
    sort = apply_sort(platforms, find, PLATFORM_SORTS, PLATFORM_DEFAULT_SORT)
    platforms = sort.queryset
    warn_unknown_sort(request, sort.unknown, entity="platform")
    platforms, page_obj, elided_page_range = paginate(platforms, find)
    #: One read serves cells, rows and references.
    page_platforms = list(platforms)
    references = references_for(page_platforms)

    hidden, picker = column_choice(request, "platforms", PLATFORM_COLUMNS)
    kept_columns, kept_cells = drop_columns(
        PLATFORM_COLUMNS,
        [
            [
                TruncatedText(platform.name),
                Icon(platform.icon),
                platform.group,
                ExternalReferenceLinks(held_by(references, platform.pk)),
                presentation.format(platform.created_at, "date"),
            ]
            for platform in page_platforms
        ],
        hidden,
    )
    data: TableData = {
        "caption": "Platforms",
        "columns": kept_columns,
        "menu_slot": True,
        "sort_terms": sort.terms,
        "rows": [
            make_row(
                *cells, key=str(platform.pk), menu=platform_row_menu(platform, origin)
            )
            for platform, cells in zip(page_platforms, kept_cells, strict=True)
        ],
        "column_picker": picker,
        "selection": {
            "filter": filter_json,
            "csrf_token": get_token(request),
            "actions": tray_actions(
                EDIT_PLATFORMS.name, REMOVE_PLATFORM.name, origin=origin
            ),
        },
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
    parsed_filter = parse_filter_dict(filter_json, PlatformFilter)
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
@require_POST
def restore_platform(request: HttpRequest, platform_id: UUID) -> HttpResponse:
    """Undo; the plain manager, since the row is removed."""
    library = cast(User, request.user).library
    platform = owned_or_404(
        Platform.objects.filter(library=library), library, id=platform_id
    )
    return restore_and_return(
        request,
        action=partial(restore_platform_by_hand, platform),
        restored=f"{platform.name} restored to your library.",
        fallback="games:list_platforms",
    )


def _still_naming(library: UserLibrary, platform: Platform) -> Node:
    """Live rows naming it, as the batch counts."""
    naming = platform_departures(library, platform)
    return Ul()[
        Li()[
            f"{naming.games} game(s), {naming.releases} release(s) and "
            f"{naming.purchases} purchase(s) still name it"
        ]
    ]


@login_required
def remove_platform(request: HttpRequest, platform_id: UUID) -> HttpResponse:
    library = cast(User, request.user).library
    platform = owned_or_404(
        Platform.objects.for_library(library), library, id=platform_id
    )
    return confirm_and_remove(
        request,
        platform,
        title="Remove platform",
        message=f"Remove {platform.name} from your library?",
        details=_still_naming(library, platform),
        fallback="games:list_platforms",
        removed=f"{platform.name} removed from your library.",
        undo="games:restore_platform",
    )


def _platform_form_page(
    request: HttpRequest,
    library: UserLibrary,
    *,
    platform: Platform | None,
    title: str,
) -> HttpResponse:
    """One Platform, and the references it states."""
    form = PlatformForm(request.POST or None, instance=platform, library=library)
    references = ReferenceSetForm(
        request.POST or None, target=platform, library=library
    )
    #: Both read, whatever either says.
    form_reads = form.is_valid()
    if references.is_valid() and form_reads:
        written = submitted_or_form_error(form, references)
        if written is not None:
            back = return_url(request, fallback="games:list_platforms")
            if platform is None:
                return CreatedRedirect(
                    back, option=platform_option(cast(Platform, written))
                )
            return redirect(back)
    return render_page(
        request,
        AddForm(
            form,
            request=request,
            fields=Fragment(FormFields(form), references_area(references)),
        ),
        title=title,
    )


@login_required
def edit_platform(request: HttpRequest, platform_id: UUID) -> HttpResponse:
    library = cast(User, request.user).library
    platform = owned_or_404(
        Platform.objects.for_library(library), library, id=platform_id
    )
    return _platform_form_page(
        request, library, platform=platform, title="Edit Platform"
    )


@login_required
def add_platform(request: HttpRequest) -> HttpResponse:
    library = cast(User, request.user).library
    return _platform_form_page(
        request, library, platform=None, title="Add New Platform"
    )
