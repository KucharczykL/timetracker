import logging
import uuid
from datetime import date, datetime, timedelta
from typing import Any, cast
from uuid import UUID

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import Max, QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse

from common.components import (
    AddForm,
    ContentContainer,
    Fragment,
    ModuleScript,
    QuickFilterBar,
    paginated_table_content,
    parse_filter_dict,
)
from common.date_time_presentation import date_time_presentation_for_request
from common.duration_presentation import (
    DurationPresentation,
    duration_format_profile,
)
from common.filter_execution import execute_filter, regex_timeout_view
from common.layout import render_page
from common.utils import paginate
from games.commands.playthrough import ActStatement
from games.filters import (
    PlaythroughFilter,
    filter_query_context_for_library,
    parse_playthrough_filter,
)
from games.forms import PlaythroughForm
from games.models import (
    Game,
    PlayerGameStatus,
    Playthrough,
    Session,
    UserLibrary,
)
from games.ownership import owned_or_404
from games.reads.playthrough_endpoints import (
    StatedEndpoint,
    restatable_days,
    stated_completion,
    stated_start,
)
from games.reads.playthrough_numbering import numbered_for
from games.reads.playthrough_runs import library_runs, live_ordinary_runs, tracked_game
from games.sorting import (
    PLAYTHROUGH_DEFAULT_SORT,
    PLAYTHROUGH_SORTS,
    apply_sort,
    parse_find_filter,
)
from games.views.filtering import (
    apply_structured_filter,
    builder_url_for,
    warn_unknown_sort,
)
from games.views.playergame_writes import record_facts_for_request
from games.views.playthrough_rows import playthrough_tabledata
from games.views.playthrough_writes import (
    record_run_for_request,
    remove_run_for_request,
    restate_run_for_request,
)
from games.views.removal import confirm_and_apply
from games.views.returns import return_url
from games.writes.playergame import new_correlation_id
from games.writes.playthrough import RunDraft
from timetracker.temporal import TemporalValue

logger = logging.getLogger("games")


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
    sessions_queryset = game.sessions.alive()

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
def list_playthroughs(request: HttpRequest) -> HttpResponse:
    library = cast(User, request.user).library
    presentation = date_time_presentation_for_request(request)
    origin = request.get_full_path()
    runs = library_runs(library).select_related("player_game__game")

    filter_json = request.GET.get("filter", "")
    if filter_json:
        playthrough_filter = apply_structured_filter(
            request, parse_playthrough_filter, filter_json
        )
        if playthrough_filter is not None:
            runs = execute_filter(
                playthrough_filter,
                runs,
                filter_query_context_for_library(library),
            )

    find = parse_find_filter(request)
    sort = apply_sort(runs, find, PLAYTHROUGH_SORTS, PLAYTHROUGH_DEFAULT_SORT)
    warn_unknown_sort(request, sort.unknown, entity="playthrough")
    page_rows, page_obj, elided_page_range = paginate(sort.queryset, find)
    page_runs = list(page_rows)
    #: One query numbers runs across these games.
    numbers = {
        numbered.pk: getattr(numbered, "display_number", None)
        for numbered in numbered_for(library, {run.player_game_id for run in page_runs})
    }
    for run in page_runs:
        run.display_number = numbers.get(run.pk)
    data = playthrough_tabledata(
        page_runs,
        presentation,
        sort_terms=sort.terms,
        sortable=True,
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
        "playthroughs", filter_json, find.sort, find.per_page_override
    )
    parsed_filter = parse_filter_dict(filter_json, PlaythroughFilter)
    quick_bar = QuickFilterBar(
        presentation=presentation,
        mode="playthroughs",
        existing=parsed_filter,
        builder_url=builder_url,
        preset_api_url=reverse("api-1.0.0:list_presets"),
        per_page_override=find.per_page_override,
    )
    content = ContentContainer()[quick_bar, content]
    return render_page(
        request,
        content,
        title="Manage playthroughs",
    )


@login_required
def add_playthrough(request: HttpRequest, game_id: UUID | None = None) -> HttpResponse:
    initial: dict[str, Any] = {}
    library = cast(User, request.user).library
    if game_id:
        # coming from add_playthrough_for_game url path
        game = owned_or_404(Game.objects.for_library(library), library, id=game_id)
        initial["game"] = game
        try:
            # First, try to get the latest session. If no sessions, then no playtime.
            latest_session = game.sessions.alive().latest("timestamp_start")
            latest_session_ts = latest_session.timestamp_start

            #: The greatest finish day a run states.
            tracked = tracked_game(library, game)
            last_finish = (
                live_ordinary_runs(library, tracked).aggregate(
                    latest=Max("completed_upper")
                )["latest"]
                if tracked is not None
                else None
            )

            if last_finish is not None:
                new_playthrough_start_date = last_finish + timedelta(days=1)
                initial["started"] = new_playthrough_start_date
                playtime_calc_start_ts = datetime.combine(
                    new_playthrough_start_date, datetime.min.time()
                )
            else:
                #: No finish day, so the earliest session.
                earliest_session_ts = (
                    game.sessions.alive().earliest("timestamp_start").timestamp_start
                )
                initial["started"] = earliest_session_ts.date()
                playtime_calc_start_ts = earliest_session_ts

            #: The end day, and the playtime span's.
            initial["ended"] = latest_session_ts.date()
            playtime_calc_end_ts = latest_session_ts

            initial["note"] = _get_formatted_playtime_for_game_sessions_in_range(
                game, playtime_calc_start_ts, playtime_calc_end_ts
            )
        except Session.DoesNotExist:
            initial["started"] = None
            initial["ended"] = None
            initial["note"] = "0h 00m"
    form = PlaythroughForm(
        request.POST or None,
        initial=initial,
        library=library,
        presentation=date_time_presentation_for_request(request),
    )
    if form.is_valid():
        game = form.cleaned_data["game"]
        correlation_id = new_correlation_id()
        if record_run_for_request(
            request, game, _recorded_draft(form), correlation_id=correlation_id
        ):
            if form.cleaned_data.get("mark_as_finished"):
                #: Discarded on purpose: a refused status
                #: toasts, and the run it belongs to stands.
                _record_completed(request, game, correlation_id)
            return redirect(
                return_url(
                    request,
                    fallback="games:view_game",
                    fallback_args=[game.id, game.url_slug],
                )
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


def _stated_act(day: date | None) -> ActStatement:
    """The act, dated where a day was given.

    The field is optional, and from_day refuses None.
    """
    return ActStatement(None if day is None else TemporalValue.from_day(day))


def _recorded_draft(form: PlaythroughForm) -> RunDraft:
    """The run this form records; both acts happened."""
    return RunDraft(
        started=_stated_act(form.cleaned_data["started"]),
        completed=_stated_act(form.cleaned_data["ended"]),
        note=form.cleaned_data["note"],
    )


def _restated_act(
    day: date | None, stated: StatedEndpoint | None
) -> ActStatement | None:
    """The act this field restates, or nothing.

    A blank field beside a stated act clears its day. A
    blank field beside no act states nothing at all, so an
    edit records no act the person never recorded.
    """
    if day is None and stated is None:
        return None
    return _stated_act(day)


def _edited_draft(form: PlaythroughForm, run: Playthrough) -> RunDraft:
    """The run this form restates onto an existing one."""
    return RunDraft(
        started=_restated_act(form.cleaned_data["started"], stated_start(run)),
        completed=_restated_act(form.cleaned_data["ended"], stated_completion(run)),
        note=form.cleaned_data["note"],
    )


#: A run this day-shaped form cannot restate.
RICHER_THAN_A_DAY = (
    "This playthrough states a date this form cannot hold, so editing it here "
    "would lose what it says."
)


def _no_run_here(request: HttpRequest, game: Game, sentence: str) -> HttpResponse:
    """Toast the sentence and leave the page."""
    messages.error(request, sentence)
    return redirect(
        return_url(
            request,
            fallback="games:view_game",
            fallback_args=[game.id, game.url_slug],
        )
    )


def _editable_runs(library: UserLibrary) -> QuerySet[Playthrough]:
    """This library's live runs, their game beside them."""
    return Playthrough.objects.select_related("player_game__game").filter(
        library=library,
        player_game__library=library,
        removed_at__isnull=True,
    )


def _record_completed(
    request: HttpRequest, game: Game, correlation_id: uuid.UUID
) -> bool:
    """State Completed for the game just finished.

    The request's correlation id, not a fresh one: the act
    and the status it implies belong to one submit. No
    reader groups events that way yet, so this changes no
    screen. It is the plumbing #683 needs.

    Answers False on a refusal, which toasted already.
    """
    return record_facts_for_request(
        request,
        game,
        status=PlayerGameStatus.COMPLETED,
        correlation_id=correlation_id,
    )


@login_required
def edit_playthrough(request: HttpRequest, playthrough_id: UUID) -> HttpResponse:
    library = cast(User, request.user).library
    run = owned_or_404(_editable_runs(library), library, id=playthrough_id)
    game = run.player_game.game
    #: Seeded from the run, never from a legacy row:
    #: nothing writes that row any more, so a second edit
    #: would restate its frozen days over the first one.
    days = restatable_days(run)
    if days is None:
        return _no_run_here(request, game, RICHER_THAN_A_DAY)
    form = PlaythroughForm(
        request.POST or None,
        initial={
            "game": game,
            "started": days.started,
            "ended": days.ended,
            "note": run.note,
        },
        library=library,
        presentation=date_time_presentation_for_request(request),
        locked_game=game,
    )
    if form.is_valid():
        correlation_id = new_correlation_id()
        if restate_run_for_request(
            request, run, _edited_draft(form, run), correlation_id=correlation_id
        ):
            if form.cleaned_data.get("mark_as_finished"):
                #: Discarded on purpose, as in add_playthrough.
                _record_completed(request, game, correlation_id)
            return redirect(
                return_url(
                    request,
                    fallback="games:view_game",
                    fallback_args=[game.id, game.url_slug],
                )
            )

    return render_page(
        request,
        AddForm(form, request=request),
        title="Edit playthrough",
        scripts=Fragment(
            ModuleScript("dist/elements/search-select.js"),
            ModuleScript("dist/elements/date-picker.js"),
        ),
    )


@login_required
def remove_playthrough(request: HttpRequest, playthrough_id: UUID) -> HttpResponse:
    library = cast(User, request.user).library
    run = owned_or_404(_editable_runs(library), library, id=playthrough_id)
    game = run.player_game.game

    def act() -> None:
        remove_run_for_request(request, run, correlation_id=new_correlation_id())

    return confirm_and_apply(
        request,
        action=act,
        title="Remove playthrough",
        message=f"Remove this playthrough of {game}?",
        confirm_label="Remove",
        fallback="games:view_game",
        fallback_args=[game.id, game.url_slug],
    )
