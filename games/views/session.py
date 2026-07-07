from typing import Any

from django.contrib.auth.decorators import login_required
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone

from common.components import (
    AddForm,
    Column,
    Div,
    FormFields,
    ICON_BUTTON_SIZE_CLASS,
    Icon,
    ModuleScript,
    NameWithIcon,
    Node,
    PopoverIf,
    SessionActions,
    SessionDeviceSelector,
    SessionTimestampButtons,
    ControlButton,
    TableData,
    TableRowData,
    make_row,
    paginated_table_content,
)
from common.layout import render_page
from common.time import (
    dateformat,
)
from games.formatting import session_time_range
from common.utils import paginate, truncate_info
from common.http import HtmxHttpRequest
from games.forms import SessionForm
from games.models import Device, Game, Session
from games.sorting import (
    SESSION_DEFAULT_SORT,
    SESSION_SORTS,
    apply_sort,
    parse_find_filter,
)
from games.views.filtering import warn_unknown_sort


def session_row_data(session: Session, device_list, csrf_token: str) -> TableRowData:
    """Canonical session-list row, the single source of truth for the list
    table. Finish/reset are driven by the <session-actions> custom element
    (PATCH /api/session/<id> + client-side row swap); Edit/Delete stay links."""
    return make_row(
        NameWithIcon(session=session),
        session_time_range(session),
        session.duration_formatted_with_mark(),
        SessionDeviceSelector(session, device_list, csrf_token),
        session.created_at.strftime(dateformat),
        SessionActions(session, csrf_token),
        id=f"session-row-{session.pk}",
    )


@login_required
def list_sessions(request: HttpRequest) -> HttpResponse:
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
    try:
        last_session = sessions.latest()
    except Session.DoesNotExist:
        last_session = None
    find = parse_find_filter(request)
    sort = apply_sort(sessions, find, SESSION_SORTS, SESSION_DEFAULT_SORT)
    sessions = sort.queryset
    warn_unknown_sort(request, sort.unknown, entity="session")
    sessions, page_obj, elided_page_range = paginate(sessions, find)
    csrf_token = get_token(request)

    resume_session_link: Node | str = ""
    if last_session and last_session.game:
        game_name = last_session.game.name
        truncation = truncate_info(game_name)
        resume_session_link = PopoverIf(
            truncation.was_truncated,
            game_name,
            ControlButton(
                href=reverse(
                    "games:list_sessions_start_session_from_session",
                    args=[last_session.pk],
                ),
                color="gray",
            )[Icon("play", size=ICON_BUTTON_SIZE_CLASS), truncation.display],
        )

    data: TableData = {
        "header_action": Div(class_="flex justify-end")[
            Div(class_="flex gap-2")[
                ControlButton(
                    href=reverse("games:add_session"),
                )[Icon("play", size=ICON_BUTTON_SIZE_CLASS), "LOG"],
                resume_session_link,
            ],
        ],
        "columns": [
            Column("Name", "name"),
            Column("Date", "date"),
            Column("Duration", "duration"),
            Column("Device", "device"),
            Column("Created", "created"),
            Column("Actions", align="right"),
        ],
        "sort_terms": sort.terms,
        "rows": [
            session_row_data(session, device_list, csrf_token) for session in sessions
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
    builder_url = builder_url_for("sessions", filter_json, find.sort)
    parsed_filter = parse_filter_dict(filter_json)
    quick_bar = QuickFilterBar(
        mode="sessions",
        existing=parsed_filter,
        builder_url=builder_url,
        preset_api_url=reverse("api-1.0.0:list_presets"),
    )
    content = ContentContainer()[quick_bar, content]
    return render_page(
        request,
        content,
        title="Manage sessions",
    )


def _timestamp_buttons(field_name: str) -> Node:
    """The now/toggle/copy helper buttons appended to a timestamp field's row."""
    this_side = "start" if field_name == "timestamp_start" else "end"
    other_side = "end" if field_name == "timestamp_start" else "start"
    return SessionTimestampButtons(
        class_="flex flex-row gap-3 justify-start mt-3",
        hx_boost="false",
    )[
        ControlButton(data_target=field_name, data_type="now")["Set to now"],
        ControlButton(data_target=field_name, data_type="toggle")["Toggle text"],
        ControlButton(data_target=field_name, data_type="copy")[
            f"Copy {this_side} value to {other_side}"
        ],
    ]


def _session_fields(form) -> Node:
    """Session form fields via the shared renderer, with timestamp helper
    buttons appended to the two timestamp rows."""
    return FormFields(
        form,
        extras={
            name: _timestamp_buttons(name)
            for name in ("timestamp_start", "timestamp_end")
        },
    )


@login_required
def add_session(request: HttpRequest, game_id: int = 0) -> HttpResponse:
    initial: dict[str, Any] = {"timestamp_start": timezone.now()}

    if request.method == "POST":
        form = SessionForm(request.POST or None, initial=initial)
        if form.is_valid():
            form.save()
            return redirect("games:list_sessions")
    else:
        if game_id:
            game = get_object_or_404(Game, id=game_id)
            form = SessionForm(
                initial={
                    **initial,
                    "game": game,
                }
            )
        else:
            form = SessionForm(initial=initial)

    # TODO: re-add custom buttons #91
    return render_page(
        request,
        AddForm(form, request=request, fields=_session_fields(form), submit_class=""),
        title="Add New Session",
        scripts=ModuleScript("dist/elements/search-select.js"),
    )


@login_required
def edit_session(request: HttpRequest, session_id: int) -> HttpResponse:
    session = get_object_or_404(Session, id=session_id)
    form = SessionForm(request.POST or None, instance=session)
    if form.is_valid():
        form.save()
        return redirect("games:list_sessions")
    return render_page(
        request,
        AddForm(form, request=request, fields=_session_fields(form), submit_class=""),
        title="Edit Session",
        scripts=ModuleScript("dist/elements/search-select.js"),
    )


def clone_session_by_id(session_id: int) -> Session:
    session = get_object_or_404(Session, id=session_id)
    clone = session
    clone.pk = None
    clone.timestamp_start = timezone.now()
    clone.timestamp_end = None
    clone.note = ""
    clone.save()
    return clone


@login_required
def new_session_from_existing_session(
    request: HtmxHttpRequest, session_id: int
) -> HttpResponse:
    clone_session_by_id(session_id)
    if request.htmx:
        # Clone adds a new row whose position depends on sort + pagination,
        # which a single-row swap cannot place — refresh the list instead.
        response = HttpResponse(status=204)
        response["HX-Refresh"] = "true"
        return response
    return redirect("games:list_sessions")


@login_required
def delete_session(request: HttpRequest, session_id: int = 0) -> HttpResponse:
    session = get_object_or_404(Session, id=session_id)
    session.delete()
    return redirect("games:list_sessions")
