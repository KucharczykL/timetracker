from typing import Any

from django.contrib.auth.decorators import login_required
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from common.components import (
    AddForm,
    BrowserTimeZoneInput,
    Column,
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
from common.layout import render_page
from common.returns import OriginUrl
from common.utils import paginate
from games.formatting import session_time_range
from games.forms import SESSION_TIMEZONE_EMBEDS, SessionForm
from games.models import Device, Game, Session
from games.sorting import (
    SESSION_DEFAULT_SORT,
    SESSION_SORTS,
    apply_sort,
    parse_find_filter,
)
from games.views.deletion import confirm_and_apply, confirm_and_delete
from games.views.filtering import warn_unknown_sort
from games.views.returns import return_url
from timetracker.settings_resolver import resolve_for_user


def session_row_data(
    session: Session,
    device_list,
    csrf_token: str,
    presentation: DateTimePresentation,
    *,
    origin: OriginUrl | None,
) -> TableRowData:
    """Canonical session-list row, the single source of truth for the list
    table. Finish/reset are driven by the <session-actions> custom element
    (PATCH /api/session/<id> + client-side row swap); Edit/Delete stay links."""
    return make_row(
        NameWithIcon(session=session),
        session_time_range(session, presentation),
        session.duration_formatted_with_mark(),
        SessionDeviceSelector(session, device_list, csrf_token),
        presentation.format(session.created_at, "date"),
        SessionActions(session, csrf_token, origin),
        id=f"session-row-{session.pk}",
    )


@login_required
def list_sessions(request: HttpRequest) -> HttpResponse:
    presentation = date_time_presentation_for_request(request)
    origin = request.get_full_path()
    sessions: QuerySet[Session] = Session.objects.select_related(
        "game", "game__platform", "device"
    )
    device_list = Device.objects.order_by("name")

    # ── Structured filter (JSON; free-text search lives here too) ──
    filter_json = request.GET.get("filter", "")
    if filter_json:
        from games.filters import parse_session_filter
        from games.views.filtering import apply_structured_filter

        session_filter = apply_structured_filter(
            request, parse_session_filter, filter_json
        )
        if session_filter is not None:
            sessions = sessions.filter(session_filter.to_q())
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
                session, device_list, csrf_token, presentation, origin=origin
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


@login_required
def add_session(request: HttpRequest, game_id: int = 0) -> HttpResponse:
    presentation = date_time_presentation_for_request(request)
    initial: dict[str, Any] = {
        # Truncated to the minute, which is as precise as the field's segments
        # go. The widget carries any sub-minute part of the value it was
        # rendered with through to submission — that is what stops an edit from
        # shifting a stored session's duration — so seeding the raw instant
        # would attach this page load's microseconds to a hand-typed time.
        "timestamp_start": timezone.now().replace(second=0, microsecond=0),
        "device": resolve_for_user(request.user, "DEFAULT_DEVICE"),
    }

    if request.method == "POST":
        form = SessionForm(
            request.POST or None, initial=initial, presentation=presentation
        )
        if form.is_valid():
            form.save()
            return redirect(return_url(request, fallback="games:list_sessions"))
    else:
        if game_id:
            game = get_object_or_404(Game, id=game_id)
            form = SessionForm(
                initial={
                    **initial,
                    "game": game,
                },
                presentation=presentation,
            )
            # Chained with a pre-filled game: focus the device field instead of
            # the already-selected game.
            form.fields["game"].widget.autofocus = False
            form.fields["device"].widget.autofocus = True
        else:
            form = SessionForm(initial=initial, presentation=presentation)

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
def edit_session(request: HttpRequest, session_id: int) -> HttpResponse:
    session = get_object_or_404(Session, id=session_id)
    initial = (
        {"device": resolve_for_user(request.user, "DEFAULT_DEVICE")}
        if session.device_id is None
        else None
    )
    form = SessionForm(
        request.POST or None,
        instance=session,
        initial=initial,
        presentation=date_time_presentation_for_request(request),
    )
    if form.is_valid():
        form.save()
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


def clone_session_by_id(session_id: int) -> Session:
    session = get_object_or_404(Session, id=session_id)
    clone = session
    clone.pk = None
    clone.timestamp_start = timezone.now()
    clone.timestamp_end = None
    # The clone's start is server-stamped now; a browser zone does not exist
    # here, and NULL already means "assume the display zone".
    clone.timestamp_start_timezone = None
    clone.timestamp_end_timezone = None
    clone.note = ""
    clone.save()
    return clone


@login_required
@require_POST
def new_session_from_existing_session(
    request: HttpRequest, session_id: int
) -> HttpResponse:
    clone_session_by_id(session_id)
    return redirect(return_url(request, fallback="games:list_sessions"))


def _posted_browser_zone(request: HttpRequest) -> str:
    """The browser's IANA zone as submitted, or "" when it is missing or
    unusable. A zone this runtime cannot resolve is not worth failing a save
    over — the endpoint simply stays unlabelled."""
    zone = zone_or_none(request.POST.get("browser_time_zone", ""))
    return zone.key if zone else ""


@login_required
@require_POST
def finish_session(request: HttpRequest, session_id: int) -> HttpResponse:
    session = get_object_or_404(Session, id=session_id)
    session.timestamp_end = timezone.now()
    session.timestamp_end_timezone = _posted_browser_zone(request)
    session.save()
    return redirect(return_url(request, fallback="games:list_sessions"))


@login_required
def reset_session(request: HttpRequest, session_id: int) -> HttpResponse:
    session = get_object_or_404(Session, id=session_id)

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
def delete_session(request: HttpRequest, session_id: int = 0) -> HttpResponse:
    session = get_object_or_404(Session, id=session_id)
    return confirm_and_delete(
        request,
        session,
        title="Delete session",
        message=f"Permanently delete this session of {session.game}?",
        fallback="games:list_sessions",
    )
