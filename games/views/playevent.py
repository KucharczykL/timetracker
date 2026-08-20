import logging
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any, cast
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import QuerySet
from django.db.models.manager import BaseManager
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse

from common.components import (
    ICON_BUTTON_SIZE_CLASS,
    AddForm,
    ButtonGroup,
    Cell,
    Column,
    ContentContainer,
    Fragment,
    Icon,
    ModuleScript,
    QuickFilterBar,
    TableData,
    TruncatedText,
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
    duration_format_profile,
)
from common.filter_execution import execute_filter, regex_timeout_view
from common.layout import render_page
from common.returns import OriginUrl, action_url
from common.utils import paginate
from games.filters import filter_query_context_for_library, parse_playevent_filter
from games.forms import PlayEventForm
from games.models import Game, PlayEvent, Session
from games.ownership import owned_or_404
from games.sorting import (
    PLAYEVENT_DEFAULT_SORT,
    PLAYEVENT_SORTS,
    SortTerm,
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

logger = logging.getLogger("games")


def create_playevent_tabledata(
    playevents: list[PlayEvent] | BaseManager[PlayEvent] | QuerySet[PlayEvent],
    presentation: DateTimePresentation,
    exclude_columns: Sequence[str] = (),
    request: HttpRequest | None = None,
    sort_terms: Sequence[SortTerm] = (),
    *,
    origin: OriginUrl | None,
) -> TableData:
    if isinstance(playevents, BaseManager):
        playevents = playevents.all()
    column_list = [
        Column("Game", "name", shrinkable=True),
        Column("Started", "started", priority=3),
        Column("Ended", "ended", priority=2),
        Column("Days to finish", "days", priority=2),
        # Free text with no natural width: on one line a single long note would
        # widen the table past anything the other columns could reclaim.
        Column("Note", wrap=True),
        Column("Created", "created"),
        Column("Actions", align="right", priority=4),
    ]
    filtered_column_list = [
        column for column in column_list if column.label not in exclude_columns
    ]
    excluded_column_indexes = [
        index
        for index, column in enumerate(column_list)
        if column.label in exclude_columns
    ]

    row_list: list[list[Cell]] = [
        [
            TruncatedText(
                playevent.game.name,
                link=reverse("games:view_game", args=[playevent.game.id]),
            ),
            presentation.format(playevent.started, "date")
            if playevent.started
            else "-",
            presentation.format(playevent.ended, "date") if playevent.ended else "-",
            str(playevent.days_to_finish) if playevent.days_to_finish else "-",
            playevent.note,
            presentation.format(playevent.created_at, "date"),
            ButtonGroup(
                [
                    {
                        "href": action_url(
                            "games:edit_playevent", playevent.pk, origin=origin
                        ),
                        "slot": Icon("edit", size=ICON_BUTTON_SIZE_CLASS),
                        "color": "gray",
                    },
                    {
                        "href": action_url(
                            "games:delete_playevent", playevent.pk, origin=origin
                        ),
                        "slot": Icon("delete", size=ICON_BUTTON_SIZE_CLASS),
                        "color": "red",
                    },
                ]
            ),
        ]
        for playevent in playevents
    ]
    filtered_row_list = [
        [column for idx, column in enumerate(row) if idx not in excluded_column_indexes]
        for row in row_list
    ]
    return {
        "caption": "Play events",
        "columns": filtered_column_list,
        "sort_terms": sort_terms,
        "rows": [make_row(*cells) for cells in filtered_row_list],
    }


def _get_formatted_playtime_for_game_sessions_in_range(
    game: Game,
    start_timestamp: datetime | None = None,
    end_timestamp: datetime | None = None,
) -> str:
    """
    Calculates and formats the total playtime for a game's sessions
    between specified start and end timestamps. If timestamps are not provided,
    it uses the earliest and latest session start times for the game.
    Returns "0h 00m" if no sessions exist for the game or if the range is invalid.
    """
    sessions_queryset = game.sessions.all()

    if not sessions_queryset.exists():
        return "0h 00m"

    actual_start_ts = (
        start_timestamp
        if start_timestamp is not None
        else sessions_queryset.earliest("timestamp_start").timestamp_start
    )
    actual_end_ts = (
        end_timestamp
        if end_timestamp is not None
        else sessions_queryset.latest("timestamp_start").timestamp_start
    )

    sessions_in_range = sessions_queryset.filter(
        timestamp_start__gte=actual_start_ts, timestamp_start__lte=actual_end_ts
    )
    # This seeds a note the user then saves, so it is stored text rather than
    # display: a per-viewer duration preference must not leak into it.
    fixed = DurationPresentation(duration_format_profile("hours_minutes"), "en-us")
    return fixed.format(sessions_in_range.total_duration_unformatted())


@login_required
@regex_timeout_view
def list_playevents(request: HttpRequest) -> HttpResponse:
    library = cast(User, request.user).library
    presentation = date_time_presentation_for_request(request)
    origin = request.get_full_path()
    playevents = PlayEvent.objects.for_library(library)

    filter_json = request.GET.get("filter", "")
    if filter_json:
        playevent_filter = apply_structured_filter(
            request, parse_playevent_filter, filter_json
        )
        if playevent_filter is not None:
            playevents = execute_filter(
                playevent_filter,
                playevents,
                filter_query_context_for_library(library),
            )

    find = parse_find_filter(request)
    sort = apply_sort(playevents, find, PLAYEVENT_SORTS, PLAYEVENT_DEFAULT_SORT)
    playevents = sort.queryset
    warn_unknown_sort(request, sort.unknown, entity="playevent")
    playevents, page_obj, elided_page_range = paginate(playevents, find)
    data = create_playevent_tabledata(
        playevents,
        presentation,
        request=request,
        sort_terms=sort.terms,
        origin=origin,
    )
    content = paginated_table_content(
        data,
        page_obj=page_obj,
        elided_page_range=elided_page_range,
        request=request,
        page_size=find.per_page,
    )
    builder_url = builder_url_for(
        "playevents", filter_json, find.sort, find.per_page_override
    )
    parsed_filter = parse_filter_dict(filter_json)
    quick_bar = QuickFilterBar(
        presentation=presentation,
        mode="playevents",
        existing=parsed_filter,
        builder_url=builder_url,
        preset_api_url=reverse("api-1.0.0:list_presets"),
        per_page_override=find.per_page_override,
    )
    content = ContentContainer()[quick_bar, content]
    return render_page(
        request,
        content,
        title="Manage play events",
    )


@login_required
def add_playevent(request: HttpRequest, game_id: UUID | None = None) -> HttpResponse:
    initial: dict[str, Any] = {}
    library = cast(User, request.user).library
    if game_id:
        # coming from add_playevent_for_game url path
        game = owned_or_404(Game.objects.for_library(library), library, id=game_id)
        initial["game"] = game
        try:
            # First, try to get the latest session. If no sessions, then no playtime.
            latest_session = game.sessions.latest("timestamp_start")
            latest_session_ts = latest_session.timestamp_start

            # Now, determine the start date for the new playevent.
            # This will be either the day after the last playevent ended, or the earliest session.
            try:
                latest_playevent = game.playevents.latest("ended")
            except PlayEvent.DoesNotExist:
                latest_playevent = None

            if latest_playevent is not None and latest_playevent.ended is not None:
                # Start the day after the last playevent ended.
                new_playevent_form_start_date = latest_playevent.ended + timedelta(
                    days=1
                )
                initial["started"] = new_playevent_form_start_date
                playtime_calc_start_ts = datetime.combine(
                    new_playevent_form_start_date, datetime.min.time()
                )
            else:
                # No previous playevent (or none with an end date), so the new
                # playevent starts from the earliest session.
                earliest_session_ts = game.sessions.earliest(
                    "timestamp_start"
                ).timestamp_start
                initial["started"] = earliest_session_ts.date()
                playtime_calc_start_ts = earliest_session_ts

            # The end date for the new PlayEvent form and playtime calculation is the latest session's start date.
            initial["ended"] = latest_session_ts.date()
            playtime_calc_end_ts = latest_session_ts

            initial["note"] = _get_formatted_playtime_for_game_sessions_in_range(
                game, playtime_calc_start_ts, playtime_calc_end_ts
            )
        except Session.DoesNotExist:
            initial["started"] = None
            initial["ended"] = None
            initial["note"] = "0h 00m"
    form = PlayEventForm(
        request.POST or None,
        initial=initial,
        library=library,
        presentation=date_time_presentation_for_request(request),
    )
    if form.is_valid():
        form.save()
        if not game_id:
            # coming from add_playevent url path
            game_id = form.instance.game.id
        return redirect(
            return_url(request, fallback="games:view_game", fallback_args=[game_id])
        )

    return render_page(
        request,
        AddForm(form, request=request),
        title="Add new playthrough",
        scripts=Fragment(
            ModuleScript("dist/elements/search-select.js"),
            ModuleScript("dist/elements/date-picker.js"),
        ),
    )


@login_required
def edit_playevent(request: HttpRequest, playevent_id: UUID) -> HttpResponse:
    library = cast(User, request.user).library
    playevent = owned_or_404(
        PlayEvent.objects.for_library(library), library, id=playevent_id
    )
    form = PlayEventForm(
        request.POST or None,
        instance=playevent,
        library=library,
        presentation=date_time_presentation_for_request(request),
    )
    if form.is_valid():
        form.save()
        return redirect(
            return_url(
                request, fallback="games:view_game", fallback_args=[playevent.game.id]
            )
        )

    return render_page(
        request,
        AddForm(form, request=request),
        title="Edit Play Event",
        scripts=Fragment(
            ModuleScript("dist/elements/search-select.js"),
            ModuleScript("dist/elements/date-picker.js"),
        ),
    )


@login_required
def delete_playevent(request: HttpRequest, playevent_id: UUID) -> HttpResponse:
    library = cast(User, request.user).library
    playevent = owned_or_404(
        PlayEvent.objects.for_library(library), library, id=playevent_id
    )
    return confirm_and_delete(
        request,
        playevent,
        title="Delete playthrough",
        message=f"Permanently delete this playthrough of {playevent.game}?",
        fallback="games:view_game",
        fallback_args=[playevent.game.id],
    )
