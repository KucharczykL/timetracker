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
    Button,
    ButtonGroup,
    Component,
    Div,
    Icon,
    ModuleScript,
    NameWithIcon,
    Popover,
    SearchField,
    SessionDeviceSelector,
    paginated_table_content,
)
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
                            url_name="games:add_session",
                            children=Button(
                                icon=True,
                                size="xs",
                                children=[Icon("play"), "LOG"],
                            ),
                        ),
                        A(
                            href=reverse(
                                "games:list_sessions_start_session_from_session",
                                args=[last_session.pk],
                            ),
                            children=Popover(
                                popover_content=last_session.game.name,
                                children=[
                                    Button(
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
    content = mark_safe(str(filter_bar) + str(content))
    return render_page(
        request,
        content,
        title="Manage sessions",
        scripts=ModuleScript("range_slider.js")
        + ModuleScript("selectable_filter.js")
        + ModuleScript("filter_bar.js"),
    )


@login_required
def search_sessions(request: HttpRequest) -> HttpResponse:
    return list_sessions(request, search_string=request.GET.get("search_string", ""))


def _session_fields(form) -> SafeText:
    """Manual per-field layout for the session form.

    Mirrors the old add_session.html: each field gets its label and widget,
    and the timestamp fields gain a row of now/toggle/copy helper buttons.
    """
    rows: list[SafeText] = []
    for field in form:
        children: list[SafeText | str] = [
            mark_safe(str(field.label_tag())),
            mark_safe(str(field)),
        ]
        if field.name in ("timestamp_start", "timestamp_end"):
            this_side = "start" if field.name == "timestamp_start" else "end"
            other_side = "end" if field.name == "timestamp_start" else "start"
            children.append(
                Component(
                    tag_name="span",
                    attributes=[
                        (
                            "class",
                            "form-row-button-group flex-row gap-3 justify-start mt-3",
                        ),
                        ("hx-boost", "false"),
                    ],
                    children=[
                        Button(
                            [("data-target", field.name), ("data-type", "now")],
                            "Set to now",
                            size="xs",
                        ),
                        Button(
                            [("data-target", field.name), ("data-type", "toggle")],
                            "Toggle text",
                            size="xs",
                        ),
                        Button(
                            [("data-target", field.name), ("data-type", "copy")],
                            f"Copy {this_side} value to {other_side}",
                            size="xs",
                        ),
                    ],
                )
            )
        rows.append(Div(children=children))
    return mark_safe("\n".join(rows))


@login_required
def add_session(request: HttpRequest, game_id: int = 0) -> HttpResponse:
    initial: dict[str, Any] = {"timestamp_start": timezone.now()}

    last = Session.objects.last()
    if last is not None:
        initial["game"] = last.game

    if request.method == "POST":
        form = SessionForm(request.POST or None, initial=initial)
        if form.is_valid():
            form.save()
            return redirect("games:list_sessions")
    else:
        if game_id:
            game = Game.objects.get(id=game_id)
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
        scripts=mark_safe(
            ModuleScript("search_select.js") + ModuleScript("add_session.js")
        ),
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
        scripts=mark_safe(
            ModuleScript("search_select.js") + ModuleScript("add_session.js")
        ),
    )


def _session_row_fragment(session: Session) -> SafeText:
    """A single session <tr> (the old list_sessions.html#session-row partial),
    returned by the inline end/clone-session HTMX endpoints."""
    name_link = Component(
        tag_name="a",
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
            ("href", reverse("games:view_game", args=[session.game.id])),
        ],
        children=[session.game.name],
    )
    name_td = Component(
        tag_name="td",
        attributes=[
            (
                "class",
                "px-2 sm:px-4 md:px-6 md:py-2 purchase-name relative align-top "
                "w-24 h-12 group",
            )
        ],
        children=[
            Component(
                tag_name="span",
                attributes=[("class", "inline-block relative")],
                children=[name_link],
            )
        ],
    )
    start_td = Component(
        tag_name="td",
        attributes=[
            ("class", "px-2 sm:px-4 md:px-6 md:py-2 font-mono hidden sm:table-cell")
        ],
        children=[date_filter(session.timestamp_start, "d/m/Y H:i")],
    )

    if not session.timestamp_end:
        end_url = reverse("games:list_sessions_end_session", args=[session.id])
        end_inner: SafeText | str = Component(
            tag_name="a",
            attributes=[
                ("href", end_url),
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
                Component(
                    tag_name="span",
                    attributes=[("class", "text-yellow-300")],
                    children=["Finish now?"],
                )
            ],
        )
    elif session.duration_manual:
        end_inner = "--"
    else:
        end_inner = date_filter(session.timestamp_end, "d/m/Y H:i")
    end_td = Component(
        tag_name="td",
        attributes=[
            ("class", "px-2 sm:px-4 md:px-6 md:py-2 font-mono hidden lg:table-cell")
        ],
        children=[end_inner],
    )
    duration_td = Component(
        tag_name="td",
        attributes=[("class", "px-2 sm:px-4 md:px-6 md:py-2 font-mono")],
        children=[session.duration_formatted()],
    )
    return Component(tag_name="tr", children=[name_td, start_td, end_td, duration_td])


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
