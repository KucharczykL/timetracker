from typing import Any, cast
from uuid import UUID, uuid7

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
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
    Session,
    UserLibrary,
)
from games.ownership import owned_or_404
from games.sorting import (
    SESSION_DEFAULT_SORT,
    SESSION_SORTS,
    apply_sort,
    parse_find_filter,
)
from games.views.filtering import warn_unknown_sort
from games.views.playergame_writes import record_facts_for_request
from games.views.removal import confirm_and_apply, confirm_and_remove
from games.views.returns import return_url
from games.writes.playergame import new_correlation_id


def session_row_data(
    session: Session,
    device_list,
    csrf_token: str,
    presentation: DateTimePresentation,
    durations: DurationPresentation,
    *,
    origin: OriginUrl | None,
) -> TableRowData:
    """Canonical session-list row, the single source of truth for the list
    table."""
    return make_row(
        NameWithIcon(session=session),
        session_time_range(session, presentation),
        Duration(
            session.duration_total,
            durations,
            id_scope=f"session-{session.pk}",
            manual=session.is_manual(),
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
    sessions: QuerySet[Session] = Session.objects.for_library(library).select_related(
        "game", "game__platform", "device"
    )
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
            )
            for session in sessions
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
    from games.views.filtering import builder_url_for

    # The quick bar is the page's only filter tier; the builder
    # entry point lives in its action group.
    filter_json = request.GET.get("filter", "")
    builder_url = builder_url_for(
        "sessions", filter_json, find.sort, find.per_page_override
    )
    parsed_filter = parse_filter_dict(filter_json)
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


def _record_played(request: HttpRequest, session: Session) -> None:
    """State Played for a game the projection calls unplayed."""
    tracked = PlayerGame.objects.filter(
        library=cast(User, request.user).library, game=session.game
    ).first()
    #: No row states nothing. record_facts() tracks it
    #: first, as it does for both sibling paths.
    if tracked is not None and tracked.status != PlayerGameStatus.UNPLAYED:
        return
    record_facts_for_request(
        request,
        session.game,
        status=PlayerGameStatus.PLAYED,
        correlation_id=new_correlation_id(),
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
        "timestamp_start": timezone.now().replace(second=0, microsecond=0),
        "device": cast(User, request.user).library.preferences.default_device,
    }

    if request.method == "POST":
        form = SessionForm(
            request.POST or None,
            initial=initial,
            library=library,
            presentation=presentation,
        )
        if form.is_valid():
            session = form.save()
            if form.cleaned_data.get("mark_as_played"):
                _record_played(request, session)
            return redirect(return_url(request, fallback="games:list_sessions"))
    else:
        if game_id:
            game = owned_or_404(Game.objects.for_library(library), library, id=game_id)
            form = SessionForm(
                initial={
                    **initial,
                    "game": game,
                },
                library=library,
                presentation=presentation,
            )
            # Chained with a pre-filled game: focus the device field instead of
            # the already-selected game.
            form.fields["game"].widget.autofocus = False
            form.fields["device"].widget.autofocus = True
        else:
            form = SessionForm(
                initial=initial,
                library=library,
                presentation=presentation,
            )

    # TODO: re-add custom buttons #91
    return render_page(
        request,
        AddForm(
            form,
            request=request,
            submit_class="",
            fields=FormFields(form, embedded=SESSION_TIMEZONE_EMBEDS),
        ),
        title="Add New Session",
        scripts=Fragment(
            ModuleScript("dist/elements/search-select.js"),
            ModuleScript("dist/elements/date-time-field.js"),
            ModuleScript("dist/elements/time-zone-row.js"),
        ),
    )


@login_required
def edit_session(request: HttpRequest, session_id: UUID) -> HttpResponse:
    library = cast(User, request.user).library
    session = owned_or_404(Session.objects.for_library(library), library, id=session_id)
    initial = (
        {"device": cast(User, request.user).library.preferences.default_device}
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
        session = form.save()
        if form.cleaned_data.get("mark_as_played"):
            _record_played(request, session)
        return redirect(return_url(request, fallback="games:list_sessions"))
    return render_page(
        request,
        AddForm(
            form,
            request=request,
            submit_class="",
            fields=FormFields(form, embedded=SESSION_TIMEZONE_EMBEDS),
        ),
        title="Edit Session",
        scripts=Fragment(
            ModuleScript("dist/elements/search-select.js"),
            ModuleScript("dist/elements/date-time-field.js"),
            ModuleScript("dist/elements/time-zone-row.js"),
        ),
    )


def clone_session_by_id(session_id: UUID, library: UserLibrary) -> Session:
    session = owned_or_404(Session.objects.for_library(library), library, id=session_id)
    clone = session
    # A loaded instance keeps its identity. Assign the promoted primary key
    # explicitly, then force an insert so a generated-key collision cannot
    # update an existing session.
    clone.id = uuid7()
    clone.timestamp_start = timezone.now()
    clone.timestamp_end = None
    # The clone's start is server-stamped now; a browser zone does not exist
    # here, and NULL already means "assume the display zone".
    clone.timestamp_start_timezone = None
    clone.timestamp_end_timezone = None
    clone.note = ""
    clone.save(force_insert=True)
    return clone


@login_required
@require_POST
def new_session_from_existing_session(
    request: HttpRequest, session_id: UUID
) -> HttpResponse:
    library = cast(User, request.user).library
    clone_session_by_id(session_id, library)
    return redirect(return_url(request, fallback="games:list_sessions"))


def _posted_browser_zone(request: HttpRequest) -> str:
    """The browser's IANA zone as submitted, or "" when it is missing or
    unusable. A zone this runtime cannot resolve is not worth failing a save
    over — the endpoint simply stays unlabelled."""
    zone = zone_or_none(request.POST.get("browser_time_zone", ""))
    return zone.key if zone else ""


@login_required
def finish_session(request: HttpRequest, session_id: UUID) -> HttpResponse:
    library = cast(User, request.user).library
    session = owned_or_404(Session.objects.for_library(library), library, id=session_id)

    def finish() -> None:
        session.timestamp_end = timezone.now()
        session.timestamp_end_timezone = _posted_browser_zone(request)
        session.save()

    return confirm_and_apply(
        request,
        action=finish,
        title="Finish session",
        message=f"Finish this running session of {session.game}?",
        confirm_label="Finish session",
        details=BrowserTimeZoneInput(),
        fallback="games:list_sessions",
    )


@login_required
def reset_session(request: HttpRequest, session_id: UUID) -> HttpResponse:
    library = cast(User, request.user).library
    session = owned_or_404(Session.objects.for_library(library), library, id=session_id)

    def reset_start_to_now() -> None:
        session.timestamp_start = timezone.now()
        session.timestamp_start_timezone = _posted_browser_zone(request)
        session.save()

    return confirm_and_apply(
        request,
        action=reset_start_to_now,
        title="Reset start time",
        message=(
            f"Reset the start time of this session of {session.game} to now? "
            "The original start time is only recoverable by editing the session."
        ),
        confirm_label="Reset to now",
        details=BrowserTimeZoneInput(),
        fallback="games:list_sessions",
    )


@login_required
def remove_session(request: HttpRequest, session_id: UUID) -> HttpResponse:
    library = cast(User, request.user).library
    session = owned_or_404(Session.objects.for_library(library), library, id=session_id)
    return confirm_and_remove(
        request,
        session,
        title="Remove session",
        message=f"Remove this session of {session.game}?",
        fallback="games:list_sessions",
    )
