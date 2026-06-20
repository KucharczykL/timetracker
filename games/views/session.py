from typing import Any

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404, redirect
from django.template.defaultfilters import date as date_filter
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import SafeText, mark_safe

from common.components import (
    A,
    AddForm,
    ButtonGroup,
    Div,
    FormFields,
    Fragment,
    Icon,
    ModuleScript,
    NameWithIcon,
    Node,
    Popover,
    SearchField,
    SessionDeviceSelector,
    SessionTimestampButtons,
    StyledButton,
    paginated_table_content,
)
from common.components.primitives import Span, Td, Tr
from common.layout import render_page
from common.time import (
    dateformat,
    local_strftime,
    timeformat,
)
from common.utils import paginate, truncate
from games.forms import SessionForm
from games.models import Device, Game, Session


@login_required
def list_sessions(request: HttpRequest, search_string: str = "") -> HttpResponse:
    sessions = Session.objects.order_by("-timestamp_start", "created_at")
    device_list = Device.objects.order_by("name")

    # ── Structured filter (JSON) ──
    filter_json = request.GET.get("filter", "")
    if filter_json:
        from games.filters import parse_session_filter

        session_filter = parse_session_filter(filter_json)
        if session_filter is not None:
            sessions = sessions.filter(session_filter.to_q())
    else:
        # ── Legacy free-text search ──
        search_string = request.GET.get("search_string", search_string)
        if search_string != "":
            sessions = sessions.filter(
                Q(game__name__icontains=search_string)
                | Q(game__name__icontains=search_string)
                | Q(game__platform__name__icontains=search_string)
                | Q(device__name__icontains=search_string)
                | Q(device__type__icontains=search_string)
            )
    try:
        last_session = sessions.latest()
    except Session.DoesNotExist:
        last_session = None
    sessions, page_obj, elided_page_range = paginate(request, sessions)

    data = {
        "header_action": Div(
            children=[
                SearchField(search_string=search_string),
                Div(
                    children=[
                        A(
                            href=reverse("games:add_session"),
                        )[
                            StyledButton(
                                icon=True,
                                size="xs",
                            )[Icon("play"), "LOG"]
                        ],
                        A(
                            href=reverse(
                                "games:list_sessions_start_session_from_session",
                                args=[last_session.pk],
                            ),
                            children=Popover(
                                popover_content=last_session.game.name,
                                children=[
                                    StyledButton(
                                        icon=True,
                                        color="gray",
                                        size="xs",
                                        children=[
                                            Icon("play"),
                                            truncate(f"{last_session.game.name}"),
                                        ],
                                    )
                                ],
                            ),
                        )
                        if last_session
                        else "",
                    ]
                ),
            ],
            attributes=[("class", "flex justify-between")],
        ),
        "columns": [
            "Name",
            "Date",
            "Duration",
            "Device",
            "Created",
            "Actions",
        ],
        "rows": [
            {
                "row_id": f"session-row-{session.pk}",
                "hx_trigger": "device-changed from:body",
                "hx_get": "",
                "hx_select": f"#session-row-{session.pk}",
                "hx_swap": "outerHTML",
                "cell_data": [
                    NameWithIcon(session=session),
                    f"{local_strftime(session.timestamp_start)}{f' — {local_strftime(session.timestamp_end, timeformat)}' if session.timestamp_end else ''}",
                    session.duration_formatted_with_mark(),
                    SessionDeviceSelector(session, device_list, get_token(request)),
                    session.created_at.strftime(dateformat),
                    ButtonGroup(
                        [
                            {
                                "href": reverse(
                                    "games:list_sessions_end_session", args=[session.pk]
                                ),
                                "slot": Icon("end"),
                                "title": "Finish session now",
                                "color": "green",
                            }
                            if session.timestamp_end is None
                            else {},
                            {
                                "href": reverse(
                                    "games:edit_session", args=[session.pk]
                                ),
                                "slot": Icon("edit"),
                                "title": "Edit",
                            },
                            {
                                "href": reverse(
                                    "games:delete_session", args=[session.pk]
                                ),
                                "slot": Icon("delete"),
                                "title": "Delete",
                                "color": "red",
                            },
                        ]
                    ),
                ],
            }
            for session in sessions
        ],
    }
    content = paginated_table_content(
        data,
        page_obj=page_obj,
        elided_page_range=elided_page_range,
        request=request,
    )
    from common.components import SessionFilterBar

    filter_json = request.GET.get("filter", "")
    filter_bar = SessionFilterBar(
        filter_json=filter_json,
        preset_list_url=reverse("games:list_presets"),
        preset_save_url=reverse("games:save_preset"),
    )
    content = Fragment(filter_bar, content)
    return render_page(
        request,
        content,
        title="Manage sessions",
    )


@login_required
def search_sessions(request: HttpRequest) -> HttpResponse:
    return list_sessions(request, search_string=request.GET.get("search_string", ""))


def _timestamp_buttons(field_name: str) -> Node:
    """The now/toggle/copy helper buttons appended to a timestamp field's row."""
    this_side = "start" if field_name == "timestamp_start" else "end"
    other_side = "end" if field_name == "timestamp_start" else "start"
    return SessionTimestampButtons(
        class_="flex flex-row gap-3 justify-start mt-3",
        hx_boost="false",
    )[
        StyledButton(data_target=field_name, data_type="now", size="xs")["Set to now"],
        StyledButton(data_target=field_name, data_type="toggle", size="xs")[
            "Toggle text"
        ],
        StyledButton(data_target=field_name, data_type="copy", size="xs")[
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
        scripts=mark_safe(ModuleScript("dist/elements/search-select.js")),
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
        scripts=mark_safe(ModuleScript("dist/elements/search-select.js")),
    )


def _session_row_fragment(session: Session) -> SafeText:
    """A single session <tr> (the old list_sessions.html#session-row partial),
    returned by the inline end/clone-session HTMX endpoints."""
    name_link = A(
        href=reverse("games:view_game", args=[session.game.id]),
        attributes=[
            (
                "class",
                "underline decoration-slate-500 sm:decoration-2 inline-block "
                "truncate max-w-20char group-hover:absolute group-hover:max-w-none "
                "group-hover:-top-8 group-hover:-left-6 group-hover:min-w-60 "
                "group-hover:px-6 group-hover:py-3.5 group-hover:bg-purple-600 "
                "group-hover:rounded-xs group-hover:outline-dashed "
                "group-hover:outline-purple-400 group-hover:outline-4 "
                "group-hover:decoration-purple-900 group-hover:text-purple-100",
            ),
        ],
        children=[session.game.name],
    )
    name_td = Td(
        attributes=[
            (
                "class",
                "px-2 sm:px-4 md:px-6 md:py-2 purchase-name relative align-top "
                "w-24 h-12 group",
            )
        ],
        children=[
            Span(
                attributes=[("class", "inline-block relative")],
                children=[name_link],
            )
        ],
    )
    start_td = Td(
        attributes=[
            ("class", "px-2 sm:px-4 md:px-6 md:py-2 font-mono hidden sm:table-cell")
        ],
        children=[date_filter(session.timestamp_start, "d/m/Y H:i")],
    )

    if not session.timestamp_end:
        end_url = reverse("games:list_sessions_end_session", args=[session.id])
        end_inner: SafeText | str = A(
            href=end_url,
            attributes=[
                ("hx-get", end_url),
                ("hx-target", "closest tr"),
                ("hx-swap", "outerHTML"),
                ("hx-indicator", "#indicator"),
                (
                    "onClick",
                    "document.querySelector('#last-session-start')"
                    ".classList.remove('invisible')",
                ),
            ],
            children=[
                Span(
                    attributes=[("class", "text-yellow-300")],
                    children=["Finish now?"],
                )
            ],
        )
    elif session.duration_manual:
        end_inner = "--"
    else:
        end_inner = date_filter(session.timestamp_end, "d/m/Y H:i")
    end_td = Td(
        attributes=[
            ("class", "px-2 sm:px-4 md:px-6 md:py-2 font-mono hidden lg:table-cell")
        ],
        children=[end_inner],
    )
    duration_td = Td(
        attributes=[("class", "px-2 sm:px-4 md:px-6 md:py-2 font-mono")],
        children=[session.duration_formatted()],
    )
    return Tr(children=[name_td, start_td, end_td, duration_td])


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
    request: HttpRequest, session_id: int
) -> HttpResponse:
    session = clone_session_by_id(session_id)
    if request.htmx:
        return HttpResponse(_session_row_fragment(session))
    return redirect("games:list_sessions")


@login_required
def end_session(request: HttpRequest, session_id: int) -> HttpResponse:
    session = get_object_or_404(Session, id=session_id)
    session.timestamp_end = timezone.now()
    session.save()
    if request.htmx:
        return HttpResponse(_session_row_fragment(session))
    return redirect("games:list_sessions")


@login_required
def delete_session(request: HttpRequest, session_id: int = 0) -> HttpResponse:
    session = get_object_or_404(Session, id=session_id)
    session.delete()
    return redirect("games:list_sessions")
