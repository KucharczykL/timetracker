from collections.abc import Sequence
from functools import partial
from typing import Any, cast
from uuid import UUID

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import QuerySet
from django.http import Http404, HttpRequest, HttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from common.components import (
    AddForm,
    BrowserTimeZoneInput,
    Column,
    Duration,
    FormFields,
    Fragment,
    ModuleScript,
    NameWithIcon,
    SessionActions,
    SessionDeviceSelector,
    TableData,
    TableRowData,
    make_row,
    paginated_table_content,
)
from common.date_time_presentation import (
    DateTimePresentation,
    date_time_presentation_for_request,
    zone_or_none,
)
from common.duration_presentation import (
    DurationPresentation,
    duration_presentation_for_request,
)
from common.filter_execution import execute_filter, regex_timeout_view
from common.layout import render_page
from common.returns import OriginUrl
from common.utils import paginate
from games.formatting import session_time_range
from games.forms import SESSION_TIMEZONE_EMBEDS, SessionForm
from games.models import (
    Device,
    Game,
    PlayerGame,
    PlayerGameStatus,
    PlayerSession,
    PlayerSessionTimingMode,
    PlaythroughKind,
    UserLibrary,
)
from games.ownership import owned_or_404
from games.reads.calendar import calendar_day_zone
from games.reads.player_sessions import (
    game_sessions,
    library_sessions,
    readable_sessions,
)
from games.reads.playthrough_numbering import display_name, numbered_for
from games.sorting import (
    SESSION_DEFAULT_SORT,
    SESSION_SORTS,
    apply_sort,
    parse_find_filter,
)
from games.views.filtering import warn_unknown_sort
from games.views.playergame_writes import record_facts_for_request
from games.views.removal import confirm_and_apply, restore_and_return
from games.views.returns import return_url
from games.writes.answers import CommandFailed
from games.writes.playergame import new_correlation_id
from games.writes.playersession import (
    SessionDraft,
    clone_session,
    end_session,
    is_running,
    latest_ordinary_run,
    record_session,
    restate_session,
)
from games.writes.playersession import (
    remove_session as remove_session_row,
)
from games.writes.playersession import (
    reset_session as reset_session_start,
)
from games.writes.playersession import (
    restore_session as restore_session_row,
)

#: What the name cell calls a session in the bucket.
IMPORTED_HISTORY_LABEL = "Imported history"

#: A run's key to the label the name cell shows beside the game.
type RunLabels = dict[UUID, str]


def run_labels_for(
    library: UserLibrary, sessions: Sequence[PlayerSession]
) -> RunLabels:
    """The run label each session shows, keyed on the run.

    Only a game holding more than one live run needs one: the ordinary
    runs counted by `numbered_for`, plus the bucket when a page row sits
    in it. One query for the page, none per row.
    """
    by_game: dict[UUID, list[UUID]] = {}
    labels: RunLabels = {}
    player_game_ids = {session.playthrough.player_game_id for session in sessions}
    for run in numbered_for(library, player_game_ids):
        by_game.setdefault(run.player_game_id, []).append(run.pk)
        labels[run.pk] = display_name(run)
    for session in sessions:
        run = session.playthrough
        if run.kind == PlaythroughKind.IMPORTED_HISTORY:
            by_game.setdefault(run.player_game_id, []).append(run.pk)
            labels[run.pk] = IMPORTED_HISTORY_LABEL
    return {
        run_id: label
        for run_id, label in labels.items()
        if any(len(runs) > 1 and run_id in runs for runs in by_game.values())
    }


def session_row_data(
    session: PlayerSession,
    device_list,
    csrf_token: str,
    presentation: DateTimePresentation,
    durations: DurationPresentation,
    *,
    origin: OriginUrl | None,
    run_label: str | None = None,
) -> TableRowData:
    """Canonical session-list row, the single source of truth for the list
    table."""
    return make_row(
        NameWithIcon(session=session, run_label=run_label),
        session_time_range(session, presentation),
        Duration(
            session.effective_duration,
            durations,
            id_scope=f"session-{session.pk}",
            manual=session.timing_mode != PlayerSessionTimingMode.TIMED,
        ),
        SessionDeviceSelector(session, device_list, csrf_token),
        presentation.format(session.created_at, "date"),
        SessionActions(session, csrf_token, origin),
        id=f"session-row-{session.pk}",
    )


@login_required
@regex_timeout_view
def list_sessions(request: HttpRequest) -> HttpResponse:
    library = cast(User, request.user).library
    presentation = date_time_presentation_for_request(request)
    durations = duration_presentation_for_request(request)
    origin = request.get_full_path()
    sessions: QuerySet[PlayerSession] = readable_sessions(library)
    device_list = Device.objects.for_library(library).order_by("name")

    # ── Structured filter (JSON; free-text search lives here too) ──
    filter_json = request.GET.get("filter", "")
    if filter_json:
        from games.filters import filter_query_context_for_library, parse_session_filter
        from games.views.filtering import apply_structured_filter

        session_filter = apply_structured_filter(
            request, parse_session_filter, filter_json
        )
        if session_filter is not None:
            sessions = execute_filter(
                session_filter,
                sessions,
                filter_query_context_for_library(library),
            )
    find = parse_find_filter(request)
    sort = apply_sort(sessions, find, SESSION_SORTS, SESSION_DEFAULT_SORT)
    sessions = sort.queryset
    warn_unknown_sort(request, sort.unknown, entity="session")
    sessions, page_obj, elided_page_range = paginate(sessions, find)
    csrf_token = get_token(request)
    page_sessions = list(sessions)
    run_labels = run_labels_for(library, page_sessions)

    data: TableData = {
        "caption": "Sessions",
        "columns": [
            Column("Name", "name", shrinkable=True),
            Column("Date", "date", priority=3),
            Column("Duration", "duration", priority=2),
            Column("Device", "device"),
            Column("Created", "created"),
            Column("Actions", align="right", priority=4),
        ],
        "sort_terms": sort.terms,
        "rows": [
            session_row_data(
                session,
                device_list,
                csrf_token,
                presentation,
                durations,
                origin=origin,
                run_label=run_labels.get(session.playthrough_id),
            )
            for session in page_sessions
        ],
    }
    content = paginated_table_content(
        data,
        page_obj=page_obj,
        elided_page_range=elided_page_range,
        request=request,
        page_size=find.per_page,
    )
    from common.components import (
        ContentContainer,
        QuickFilterBar,
        parse_filter_dict,
    )
    from games.filters import PlayerSessionFilter
    from games.views.filtering import builder_url_for

    # The quick bar is the page's only filter tier; the builder
    # entry point lives in its action group.
    filter_json = request.GET.get("filter", "")
    builder_url = builder_url_for(
        "sessions", filter_json, find.sort, find.per_page_override
    )
    parsed_filter = parse_filter_dict(filter_json, PlayerSessionFilter)
    quick_bar = QuickFilterBar(
        presentation=presentation,
        mode="sessions",
        existing=parsed_filter,
        builder_url=builder_url,
        preset_api_url=reverse("api-1.0.0:list_presets"),
        per_page_override=find.per_page_override,
    )
    content = ContentContainer()[quick_bar, content]
    return render_page(
        request,
        content,
        title="Manage sessions",
    )


def _record_played(request: HttpRequest, game: Game) -> None:
    """State Played for a game the projection calls unplayed."""
    tracked = PlayerGame.objects.filter(
        library=cast(User, request.user).library, game=game
    ).first()
    #: No row states nothing. record_facts() tracks it
    #: first, as it does for both sibling paths.
    if tracked is not None and tracked.status != PlayerGameStatus.UNPLAYED:
        return
    record_facts_for_request(
        request,
        game,
        status=PlayerGameStatus.PLAYED,
        correlation_id=new_correlation_id(),
    )


#: The scripts the form's widgets need; they render to text, so no Media bubbles.
SESSION_FORM_SCRIPTS = (
    "dist/elements/search-select.js",
    "dist/elements/date-time-field.js",
    "dist/elements/time-zone-row.js",
    "dist/elements/date-picker.js",
    "dist/elements/playthrough-select.js",
)


def _session_draft(form: SessionForm, library: UserLibrary) -> SessionDraft:
    """What the valid form states, in the library's calendar."""
    device = form.cleaned_data.get("device")
    return SessionDraft(
        playthrough_id=form.cleaned_data["playthrough"].pk,
        timing=form.timing_statement(calendar_day_zone(library).key),
        device_id=None if device is None else device.pk,
        note=form.cleaned_data["note"],
        emulated=form.cleaned_data["emulated"],
    )


def _render_session_form(request: HttpRequest, form: SessionForm, title: str):
    return render_page(
        request,
        AddForm(
            form,
            request=request,
            submit_class="",
            fields=FormFields(form, embedded=SESSION_TIMEZONE_EMBEDS),
        ),
        title=title,
        scripts=Fragment(*(ModuleScript(path) for path in SESSION_FORM_SCRIPTS)),
    )


@login_required
def add_session(request: HttpRequest, game_id: UUID | None = None) -> HttpResponse:
    presentation = date_time_presentation_for_request(request)
    library = cast(User, request.user).library
    initial: dict[str, Any] = {
        # Truncated to the minute, which is as precise as the field's segments
        # go. The widget carries any sub-minute part of the value it was
        # rendered with through to submission — that is what stops an edit from
        # shifting a stored session's duration — so seeding the raw instant
        # would attach this page load's microseconds to a hand-typed time.
        "started_at": timezone.now().replace(second=0, microsecond=0),
        "device": library.preferences.default_device,
    }
    if game_id:
        game = owned_or_404(Game.objects.for_library(library), library, id=game_id)
        initial["game"] = game
        run = latest_ordinary_run(library, game)
        if run is not None:
            initial["playthrough"] = run.pk

    if request.method == "POST":
        form = SessionForm(
            request.POST, initial=initial, library=library, presentation=presentation
        )
        if form.is_valid():
            game = form.cleaned_data["game"]
            try:
                record_session(
                    cast(User, request.user),
                    _session_draft(form, library),
                    correlation_id=new_correlation_id(),
                )
            except CommandFailed as failure:
                messages.error(request, failure.message)
            else:
                if form.cleaned_data.get("mark_as_played"):
                    _record_played(request, game)
                return redirect(return_url(request, fallback="games:list_sessions"))
    else:
        form = SessionForm(initial=initial, library=library, presentation=presentation)
        if game_id:
            # Chained with a pre-filled game: focus the device field instead of
            # the already-selected game.
            form.fields["game"].widget.autofocus = False
            form.fields["device"].widget.autofocus = True

    # TODO: re-add custom buttons #91
    return _render_session_form(request, form, "Add New Session")


def _library_session(request: HttpRequest, session_id: UUID) -> PlayerSession:
    library = cast(User, request.user).library
    return owned_or_404(
        library_sessions(library).select_related("playthrough__player_game__game"),
        library,
        id=session_id,
    )


@login_required
def edit_session(request: HttpRequest, session_id: UUID) -> HttpResponse:
    library = cast(User, request.user).library
    session = _library_session(request, session_id)
    initial = (
        {"device": library.preferences.default_device}
        if session.device_id is None
        else None
    )
    form = SessionForm(
        request.POST or None,
        instance=session,
        initial=initial,
        library=library,
        presentation=date_time_presentation_for_request(request),
    )
    if form.is_valid():
        game = form.cleaned_data["game"]
        try:
            restate_session(
                cast(User, request.user),
                session,
                _session_draft(form, library),
                correlation_id=new_correlation_id(),
            )
        except CommandFailed as failure:
            messages.error(request, failure.message)
        else:
            if form.cleaned_data.get("mark_as_played"):
                _record_played(request, game)
            return redirect(return_url(request, fallback="games:list_sessions"))
    return _render_session_form(request, form, "Edit Session")


@login_required
@require_POST
def resume_session(request: HttpRequest, game_id: UUID) -> HttpResponse:
    """Start a session now at the game, as its last session was played."""
    library = cast(User, request.user).library
    game = owned_or_404(Game.objects.for_library(library), library, id=game_id)
    last = game_sessions(library, game).order_by("-sort_instant", "-id").first()
    try:
        clone_session(
            cast(User, request.user),
            game,
            device_id=None if last is None else last.device_id,
            emulated=False if last is None else last.emulated,
            correlation_id=new_correlation_id(),
        )
    except CommandFailed as failure:
        messages.error(request, failure.message)
    return redirect(return_url(request, fallback="games:list_sessions"))


def _posted_browser_zone(request: HttpRequest) -> str | None:
    """The browser's IANA zone as submitted, or None when it is missing or
    unusable. A zone this runtime cannot resolve is not worth failing a save
    over — the endpoint simply stays unlabelled."""
    zone = zone_or_none(request.POST.get("browser_time_zone", ""))
    return zone.key if zone else None


def _game_name(session: PlayerSession) -> str:
    return session.playthrough.player_game.game.name


@login_required
def finish_session(request: HttpRequest, session_id: UUID) -> HttpResponse:
    session = _library_session(request, session_id)

    def finish() -> None:
        end_session(
            cast(User, request.user),
            session,
            ended_at=timezone.now(),
            ended_at_zone=_posted_browser_zone(request),
            correlation_id=new_correlation_id(),
        )

    return confirm_and_apply(
        request,
        action=finish,
        title="Finish session",
        message=f"Finish this running session of {_game_name(session)}?",
        confirm_label="Finish session",
        details=BrowserTimeZoneInput(),
        fallback="games:list_sessions",
    )


@login_required
def reset_session(request: HttpRequest, session_id: UUID) -> HttpResponse:
    session = _library_session(request, session_id)
    #: Offered on a running Timed row alone: a finished one is corrected.
    if not is_running(session):
        raise Http404("No such session.")

    def reset_start_to_now() -> None:
        reset_session_start(
            cast(User, request.user),
            session,
            started_at=timezone.now(),
            started_at_zone=_posted_browser_zone(request),
            correlation_id=new_correlation_id(),
        )

    return confirm_and_apply(
        request,
        action=reset_start_to_now,
        title="Reset start time",
        message=(
            f"Reset the start time of this session of {_game_name(session)} to now? "
            "The original start time is only recoverable by editing the session."
        ),
        confirm_label="Reset to now",
        details=BrowserTimeZoneInput(),
        fallback="games:list_sessions",
    )


@login_required
def remove_session(request: HttpRequest, session_id: UUID) -> HttpResponse:
    session = _library_session(request, session_id)
    return confirm_and_apply(
        request,
        action=partial(
            remove_session_row,
            cast(User, request.user),
            session,
            correlation_id=new_correlation_id(),
        ),
        title="Remove session",
        message=f"Remove this session of {_game_name(session)}?",
        confirm_label="Remove",
        fallback="games:list_sessions",
        removed="Session removed.",
        undo="games:restore_session",
        undo_args=[session.pk],
    )


@login_required
@require_POST
def restore_session(request: HttpRequest, session_id: UUID) -> HttpResponse:
    """Undo: the row is removed, so the plain manager resolves it."""
    library = cast(User, request.user).library
    session = owned_or_404(
        PlayerSession.objects.filter(library=library), library, id=session_id
    )
    return restore_and_return(
        request,
        action=partial(
            restore_session_row,
            cast(User, request.user),
            session,
            correlation_id=new_correlation_id(),
        ),
        restored="Session restored.",
        fallback="games:list_sessions",
    )
