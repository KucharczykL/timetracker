"""The Historical tab of the Playtime page."""

from collections.abc import Mapping, Sequence
from typing import cast

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from django.middleware.csrf import get_token
from django.urls import reverse

from common.components import (
    Badge,
    BadgeTone,
    Cell,
    Column,
    ColumnKey,
    ContentContainer,
    DropdownLinkItem,
    Duration,
    Fragment,
    NameWithIcon,
    Node,
    PlaytimeTabs,
    QuickFilterBar,
    RowActionMenu,
    Span,
    TableData,
    make_row,
    paginated_table_content,
    parse_filter_dict,
    row_summary,
)
from common.date_time_presentation import (
    DateTimePresentation,
    date_time_presentation_for_request,
)
from common.duration_presentation import (
    DurationPresentation,
    duration_presentation_for_request,
)
from common.filter_execution import execute_filter, regex_timeout_view
from common.layout import render_page
from common.returns import OriginUrl, action_url
from common.sorting import SortKey, SortTerm
from common.temporal_presentation import TemporalText, present_temporal_value
from common.utils import paginate
from games.bulk_removal import REMOVE_RECORD
from games.bulk_tray import tray_actions
from games.filters import (
    HistoricalPlaytimeFilter,
    filter_query_context_for_library,
    parse_historical_playtime_filter,
)
from games.models import HistoricalPlaytime, HistoricalPlaytimeProvenance
from games.reads.historical_playtime_page import (
    RunLabels,
    listed_records,
    record_run_labels,
    run_labels_for,
)
from games.sorting import (
    HISTORICAL_PLAYTIME_DEFAULT_SORT,
    HISTORICAL_PLAYTIME_SORTS,
    apply_sort,
    parse_find_filter,
)
from games.views.filtering import (
    apply_structured_filter,
    builder_url_for,
    warn_unknown_sort,
)

#: Importer-written provenance gets the brand tone.
PROVENANCE_TONES: Mapping[str, BadgeTone] = {
    HistoricalPlaytimeProvenance.ESTIMATED: "neutral",
    HistoricalPlaytimeProvenance.MANUALLY_ENTERED: "neutral",
    HistoricalPlaytimeProvenance.EXTERNALLY_MEASURED: "brand",
}


def _runs_cell(record: HistoricalPlaytime, labels: RunLabels) -> Node:
    names = record_run_labels(record, labels)
    text = Span()[", ".join(names)]
    if len(names) < 2:
        return text
    return Fragment(
        text,
        Badge("shared", size="sm", tone="neutral", extra_class="ms-2"),
    )


def record_row_menu(
    record: HistoricalPlaytime,
    presentation: DateTimePresentation,
    origin: OriginUrl | None,
) -> Node:
    """Edit and Remove, back to the origin.

    The label names the day: Game detail repeats one game.
    """
    return RowActionMenu(
        [
            DropdownLinkItem(
                action_url("games:edit_historical_playtime", record.pk, origin=origin),
                "Edit",
                icon="edit",
            ),
            DropdownLinkItem(
                action_url(
                    "games:remove_historical_playtime", record.pk, origin=origin
                ),
                REMOVE_RECORD.label,
                icon="delete",
                danger=True,
            ),
        ],
        label=(
            f"{record.player_game.game.name}, "
            f"{present_temporal_value(record.when, presentation)} actions"
        ),
        id=f"record-menu-{record.pk}",
    )


#: The list page's sort keys, by label.
_SORT_KEYS: Mapping[str, SortKey] = {
    "Name": "name",
    "When": "when",
    "Duration": "duration",
    "Provenance": "provenance",
    "Device": "device",
    "Created": "created",
}


def historical_playtime_columns(*, sortable: bool) -> list[Column]:
    """The record table's columns, in declaration order."""

    def column(label: str, key: ColumnKey, **options: object) -> Column:
        return Column(
            label,
            _SORT_KEYS.get(label) if sortable else None,
            key=key,
            **options,  # type: ignore[arg-type]
        )

    return [
        column("Name", "name", shrinkable=True, hideable=False),
        #: Shrinkable as well: it leads the table Game
        #: detail renders, and the summary under a cell
        #: that cannot shrink widens the whole table.
        column("When", "when", shrinkable=True, priority=3),
        column("Duration", "duration", priority=2),
        column("Provenance", "provenance", priority=2),
        column("Playthroughs", "playthroughs", priority=1),
        column("Device", "device"),
        column("Created", "created"),
    ]


def historical_playtime_tabledata(
    records: Sequence[HistoricalPlaytime],
    labels: RunLabels,
    presentation: DateTimePresentation,
    durations: DurationPresentation,
    exclude_columns: Sequence[str] = (),
    *,
    origin: OriginUrl | None,
    sort_terms: Sequence[SortTerm] = (),
    sortable: bool = False,
    caption: str = "Historical playtime",
) -> TableData:
    """Rows for the records; caller states sorting.

    Both pages read this builder, so one drop order
    serves both. The Playthroughs column is not
    sortable on either.
    """

    column_list = historical_playtime_columns(sortable=sortable)
    kept_columns = [
        column for column in column_list if column.label not in exclude_columns
    ]
    dropped_indexes = [
        index
        for index, column in enumerate(column_list)
        if column.label in exclude_columns
    ]

    row_list: list[list[Cell]] = [
        [
            NameWithIcon(game=record.player_game.game),
            TemporalText(record.when, presentation),
            Duration(
                record.duration,
                durations,
                id_scope=f"record-{record.pk}",
                manual=True,
            ),
            Badge(
                record.get_provenance_display(),
                size="sm",
                tone=PROVENANCE_TONES[record.provenance],
            ),
            _runs_cell(record, labels),
            record.device.name if record.device else "No device",
            presentation.format(record.created_at, "date"),
        ]
        for record in records
    ]
    kept_rows = [
        [cell for index, cell in enumerate(row) if index not in dropped_indexes]
        for row in row_list
    ]
    return {
        "caption": caption,
        "columns": kept_columns,
        "sort_terms": sort_terms,
        "rows": [
            make_row(
                *cells,
                id=f"record-row-{record.pk}",
                key=str(record.pk),
                menu=record_row_menu(record, presentation, origin),
                summary=_record_summary(
                    record,
                    labels,
                    presentation,
                    durations,
                    with_when="Name" not in exclude_columns,
                ),
            )
            for record, cells in zip(records, kept_rows, strict=True)
        ],
    }


def _record_summary(
    record: HistoricalPlaytime,
    labels: RunLabels,
    presentation: DateTimePresentation,
    durations: DurationPresentation,
    *,
    with_when: bool,
) -> str:
    """The second line, below md, where the columns went.

    The identity cell decides: the list leads with the
    game and states the day below it, Game detail leads
    with the day and spends the line on the rest.
    """
    device = record.device.name if record.device else None
    if with_when:
        return row_summary(
            _when_part(record, presentation),
            durations.format(record.duration),
            device,
        )
    return row_summary(
        durations.format(record.duration),
        record.get_provenance_display(),
        _runs_part(record, labels),
        device,
    )


def _when_part(
    record: HistoricalPlaytime, presentation: DateTimePresentation
) -> str | None:
    """A day nobody knows states no part."""
    if record.when is None or record.when.is_unknown:
        return None
    return present_temporal_value(record.when, presentation)


def _runs_part(record: HistoricalPlaytime, labels: RunLabels) -> str | None:
    """The first run, and how many more.

    A comma-joined list inside a comma-joined line reads
    as one list of facts, so the rest are counted.
    """
    names = record_run_labels(record, labels)
    if not names:
        return None
    if len(names) == 1:
        return names[0]
    return f"{names[0]} and {len(names) - 1} more"


@login_required
@regex_timeout_view
def list_historical_playtime(request: HttpRequest) -> HttpResponse:
    library = cast(User, request.user).library
    presentation = date_time_presentation_for_request(request)
    durations = duration_presentation_for_request(request)
    records: QuerySet[HistoricalPlaytime] = listed_records(library)

    filter_json = request.GET.get("filter", "")
    if filter_json:
        record_filter = apply_structured_filter(
            request, parse_historical_playtime_filter, filter_json
        )
        if record_filter is not None:
            records = execute_filter(
                record_filter,
                records,
                filter_query_context_for_library(library),
            )

    find = parse_find_filter(request)
    sort = apply_sort(
        records, find, HISTORICAL_PLAYTIME_SORTS, HISTORICAL_PLAYTIME_DEFAULT_SORT
    )
    warn_unknown_sort(request, sort.unknown, entity="historical playtime")
    page_rows, page_obj, elided_page_range = paginate(sort.queryset, find)
    page_records = list(page_rows)
    data = historical_playtime_tabledata(
        page_records,
        run_labels_for(library, page_records),
        presentation,
        durations,
        origin=request.get_full_path(),
        sort_terms=sort.terms,
        sortable=True,
    )
    data["selection"] = {
        "filter": filter_json,
        "csrf_token": get_token(request),
        "actions": tray_actions(REMOVE_RECORD.name, origin=request.get_full_path()),
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
        mode="historical_playtime",
        existing=parse_filter_dict(filter_json, HistoricalPlaytimeFilter),
        builder_url=builder_url_for(
            "historical_playtime", filter_json, find.sort, find.per_page_override
        ),
        preset_api_url=reverse("api-1.0.0:list_presets"),
        per_page_override=find.per_page_override,
    )
    content = ContentContainer()[PlaytimeTabs("historical"), quick_bar, table]
    return render_page(request, content, title="Historical playtime")


__all__ = ["list_historical_playtime"]
