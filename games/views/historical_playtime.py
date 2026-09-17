"""The Historical tab of the Playtime page."""

from collections.abc import Mapping, Sequence
from typing import cast

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import Prefetch
from django.http import HttpRequest, HttpResponse
from django.urls import reverse

from common.components import (
    Badge,
    BadgeTone,
    Column,
    ContentContainer,
    Duration,
    Fragment,
    NameWithIcon,
    Node,
    PlaytimeTabs,
    QuickFilterBar,
    Span,
    TableData,
    make_row,
    paginated_table_content,
    parse_filter_dict,
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
from common.sorting import SortTerm
from common.temporal_presentation import TemporalText
from common.utils import paginate
from games.filters import (
    HistoricalPlaytimeFilter,
    filter_query_context_for_library,
    parse_historical_playtime_filter,
)
from games.models import (
    HistoricalPlaytime,
    HistoricalPlaytimeProvenance,
    HistoricalPlaytimeRun,
    UserLibrary,
)
from games.reads.historical_playtime_records import readable_records
from games.reads.playthrough_numbering import display_name, numbered_for
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

type RunLabel = str  # e.g. "Playthrough 2"

#: Importers write this one; it stands apart.
PROVENANCE_TONES: Mapping[str, BadgeTone] = {
    HistoricalPlaytimeProvenance.ESTIMATED: "neutral",
    HistoricalPlaytimeProvenance.MANUALLY_ENTERED: "neutral",
    HistoricalPlaytimeProvenance.EXTERNALLY_MEASURED: "brand",
}


def readable_list(library: UserLibrary):
    """The row path; runs in one query."""
    return readable_records(library).prefetch_related(
        Prefetch(
            "runs",
            queryset=HistoricalPlaytimeRun.objects.order_by("playthrough_id"),
        )
    )


def run_labels_for(
    library: UserLibrary, records: Sequence[HistoricalPlaytime]
) -> dict[object, RunLabel]:
    """Each run's name, numbered across its game."""
    return {
        run.pk: display_name(run)
        for run in numbered_for(library, {record.player_game_id for record in records})
    }


def _runs_cell(record: HistoricalPlaytime, labels: Mapping[object, RunLabel]) -> Node:
    runs = list(record.runs.all())
    names = ", ".join(labels[run.playthrough_id] for run in runs)
    if len(runs) < 2:
        return Span()[names]
    return Fragment(
        Span()[names],
        Badge("shared", size="sm", tone="neutral", extra_class="ms-2"),
    )


def historical_playtime_tabledata(
    records: Sequence[HistoricalPlaytime],
    labels: Mapping[object, RunLabel],
    presentation: DateTimePresentation,
    durations: DurationPresentation,
    *,
    sort_terms: Sequence[SortTerm] = (),
) -> TableData:
    """Rows for the records, one per record."""
    return {
        "caption": "Historical playtime",
        "columns": [
            Column("Name", "name", shrinkable=True),
            Column("When", "when", priority=3),
            Column("Duration", "duration", priority=2),
            Column("Provenance", "provenance", priority=2),
            Column("Runs", priority=1),
            Column("Device", "device"),
            Column("Created", "created"),
        ],
        "sort_terms": sort_terms,
        "rows": [
            make_row(
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
                id=f"record-row-{record.pk}",
            )
            for record in records
        ],
    }


@login_required
@regex_timeout_view
def list_historical_playtime(request: HttpRequest) -> HttpResponse:
    library = cast(User, request.user).library
    presentation = date_time_presentation_for_request(request)
    durations = duration_presentation_for_request(request)
    records = readable_list(library)

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
        sort_terms=sort.terms,
    )
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
