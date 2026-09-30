"""The Games page's Library tab: every copy."""

from typing import cast

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from django.middleware.csrf import get_token
from django.urls import reverse

from common.components import (
    Column,
    ContentContainer,
    ControlButton,
    GameLink,
    GamesTabs,
    Icon,
    QuickFilterBar,
    TableData,
    drop_columns,
    make_row,
    paginated_table_content,
    parse_filter_dict,
)
from common.components.primitives import ICON_BUTTON_SIZE_CLASS
from common.date_time_presentation import (
    DateTimePresentation,
    date_time_presentation_for_request,
)
from common.filter_execution import execute_filter, regex_timeout_view
from common.layout import render_page
from common.returns import action_url
from common.temporal_presentation import present_temporal_value
from common.utils import paginate
from games.bulk_entry_edit import ENTRY_EDIT
from games.bulk_removal import REMOVE_ENTRY
from games.bulk_tray import tray_actions
from games.end_ways import END_WAY_LABELS, EndWay
from games.endpoints import ENTRY_ACCESS_END
from games.filters import (
    LibraryEntryFilter,
    filter_query_context_for_library,
    parse_entry_filter,
)
from games.list_columns import column_choice
from games.models import EntryAccess, EntryFormat, LibraryEntry
from games.reads.endpoints import stated, way_of
from games.reads.entries import library_entries
from games.reads.releases import platform_words
from games.sorting import ENTRY_DEFAULT_SORT, ENTRY_SORTS, apply_sort, parse_find_filter
from games.views.entry_menu import entry_row_menu
from games.views.filtering import (
    apply_structured_filter,
    builder_url_for,
    warn_unknown_sort,
)

ENTRY_COLUMNS: list[Column] = [
    Column("Game", "name", key="game", hideable=False),
    Column("Platform", "platform", priority=2, key="platform"),
    #: What a copy is comes first.
    Column("Access", "access", priority=3, key="access"),
    Column("Format", "format", key="format"),
    Column("Acquired", "acquired", key="acquired"),
    Column("Access ended", "ended", priority=2, key="ended"),
    Column("Note", key="note", wrap=True, hidden_by_default=True),
    Column("Created", "created", key="created", hidden_by_default=True),
]


def _ended_cell(entry: LibraryEntry, presentation: DateTimePresentation) -> str:
    """Way · day; blank while held."""
    ended = stated(entry, ENTRY_ACCESS_END)
    if ended is None:
        return ""
    #: An unstated way: the day alone.
    way = "" if way_of(ended) == EndWay.UNSTATED else END_WAY_LABELS[way_of(ended)]
    day = "" if ended.when is None else present_temporal_value(ended.when, presentation)
    return " · ".join(part for part in (way, day) if part) or "Ended"


@login_required
@regex_timeout_view
def list_library(request: HttpRequest) -> HttpResponse:
    library = cast(User, request.user).library
    presentation = date_time_presentation_for_request(request)
    origin = request.get_full_path()
    entries: QuerySet[LibraryEntry] = library_entries(library).select_related(
        "player_game__game", "release__platform"
    )

    filter_json = request.GET.get("filter", "")
    if filter_json:
        entry_filter = apply_structured_filter(request, parse_entry_filter, filter_json)
        if entry_filter is not None:
            entries = execute_filter(
                entry_filter, entries, filter_query_context_for_library(library)
            )

    find = parse_find_filter(request)
    sort = apply_sort(entries, find, ENTRY_SORTS, ENTRY_DEFAULT_SORT)
    warn_unknown_sort(request, sort.unknown, entity="copy")
    page, page_obj, elided_page_range = paginate(sort.queryset, find)
    #: One read serves cells and rows.
    page_entries: list[LibraryEntry] = list(page)

    csrf_token = get_token(request)
    hidden, picker = column_choice(request, "entries", ENTRY_COLUMNS)
    kept_columns, kept_cells = drop_columns(
        ENTRY_COLUMNS,
        [
            [
                GameLink(entry.player_game.game, entry.player_game.game.name),
                platform_words(entry.release),
                EntryAccess(entry.access).label,
                EntryFormat(entry.format).label,
                ""
                if entry.acquired is None
                else present_temporal_value(entry.acquired, presentation),
                _ended_cell(entry, presentation),
                entry.note,
                presentation.format(entry.created_at, "date"),
            ]
            for entry in page_entries
        ],
        hidden,
    )
    data: TableData = {
        "caption": "Library",
        "columns": kept_columns,
        #: Every row carries its menu.
        "menu_slot": True,
        "sort_terms": sort.terms,
        "rows": [
            make_row(
                *cells,
                key=str(entry.pk),
                menu=entry_row_menu(entry, origin, csrf_token),
            )
            for entry, cells in zip(page_entries, kept_cells, strict=True)
        ],
        "column_picker": picker,
        "selection": {
            "filter": filter_json,
            "csrf_token": csrf_token,
            "actions": tray_actions(ENTRY_EDIT.name, REMOVE_ENTRY.name, origin=origin),
        },
    }
    table = paginated_table_content(
        data,
        page_obj=page_obj,
        elided_page_range=elided_page_range,
        request=request,
        page_size=find.per_page,
    )
    quick_bar = QuickFilterBar(
        presentation=presentation,
        mode="entries",
        existing=parse_filter_dict(filter_json, LibraryEntryFilter),
        preset_api_url=reverse("api-1.0.0:list_presets"),
        builder_url=builder_url_for(
            "entries", filter_json, find.sort, find.per_page_override
        ),
        per_page_override=find.per_page_override,
    )
    add = ControlButton(
        href=action_url("games:add_to_library", origin=origin), color="gray"
    )[Icon("plus", size=ICON_BUTTON_SIZE_CLASS), "Add to library"]
    content = ContentContainer()[GamesTabs("library", trailing=add), quick_bar, table]
    return render_page(request, content, title="Manage library")
