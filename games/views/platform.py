from typing import cast
from uuid import UUID

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
    ExternalReferenceLinks,
    FormFields,
    Fragment,
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
from common.filter_execution import execute_filter, regex_timeout_view
from common.layout import render_page
from common.returns import action_url
from common.utils import paginate
from games.filters import filter_query_context_for_library, parse_platform_filter
from games.forms import PlatformForm
from games.models import Platform, UserLibrary
from games.ownership import owned_or_404
from games.reads.external_references import held_by, references_for
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
from games.views.reference_section import references_area
from games.views.removal import confirm_and_remove
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
    references = references_for(list(platforms))

    data: TableData = {
        "caption": "Platforms",
        "columns": [
            Column("Name", "name"),
            Column("Icon", priority=2),
            Column("Group", "group", priority=2),
            Column("References", priority=2),
            Column("Created", "created"),
            Column("Actions", align="right", priority=3),
        ],
        "sort_terms": sort.terms,
        "rows": [
            make_row(
                TruncatedText(platform.name),
                Icon(platform.icon),
                platform.group,
                ExternalReferenceLinks(held_by(references, platform.pk)),
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
                                "games:remove_platform", platform.pk, origin=origin
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
        details=Ul()[
            Li()[
                f"{platform.game_set.count()} game(s) and "
                f"{platform.purchase_set.count()} purchase(s) still name it"
            ]
        ],
        fallback="games:list_platforms",
    )


def _platform_form_page(
    request: HttpRequest,
    library: UserLibrary,
    *,
    platform: Platform | None,
    title: str,
) -> HttpResponse:
    """Add and Edit: one Platform, and the references it states.

    `platform` is None on Add, where the row does not exist yet;
    `submitted_or_form_error` names it to the reference write once
    the save has made it.
    """
    form = PlatformForm(request.POST or None, instance=platform, library=library)
    references = ReferenceSetForm(
        request.POST or None, target=platform, library=library
    )
    #: Both read; a form the other's refusal never reached states no
    #: sentence of its own.
    form_reads = form.is_valid()
    if (
        references.is_valid()
        and form_reads
        and submitted_or_form_error(form, references) is not None
    ):
        return redirect(return_url(request, fallback="games:list_platforms"))
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
