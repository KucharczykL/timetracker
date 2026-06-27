from typing import Any

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q, QuerySet
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404, redirect
from django.template.defaultfilters import date as date_filter
from django.urls import reverse

from common.components import (
    CONTENT_MAX_WIDTH_CLASS,
    H1,
    A,
    AddForm,
    ButtonGroup,
    Column,
    CsrfInput,
    Div,
    Element,
    FilterBar,
    Fragment,
    GameStatus,
    GameStatusSelector,
    Icon,
    LinkedPurchase,
    Modal,
    ModuleScript,
    NameWithIcon,
    Node,
    Popover,
    PopoverTruncated,
    PurchasePrice,
    Safe,
    SearchField,
    StyledTable,
    StyledButton,
    TableData,
    Ul,
    make_row,
    paginated_table_content,
)
from common.components.primitives import Li, P, Span, Strong
from common.layout import render_page
from common.time import (
    dateformat,
    format_duration,
    local_strftime,
)
from common.utils import build_dynamic_filter, paginate, safe_division
from games.filters import (
    PlayEventFilter,
    PurchaseFilter,
    SessionFilter,
    filter_url,
    parse_game_filter,
)
from games.forms import GameForm
from games.models import Game, GameStatusChange
from games.sorting import GAME_DEFAULT_SORT, GAME_SORTS, apply_sort, parse_find_filter
from games.views.general import use_custom_redirect
from games.views.playevent import create_playevent_tabledata
from games.formatting import session_time_range


@login_required
def list_games(request: HttpRequest, search_string: str = "") -> HttpResponse:
    games = Game.objects.select_related("platform")

    # ── Structured filter (Stash-style JSON) ──
    filter_json = request.GET.get("filter", "")
    if filter_json:
        game_filter = parse_game_filter(filter_json)
        if game_filter is not None:
            games = games.filter(game_filter.to_q())
    else:
        # ── Legacy free-text search ──
        search_string = request.GET.get("search_string", search_string)
        if search_string != "":
            filters = [
                Q(name__icontains=search_string),
                Q(sort_name__icontains=search_string),
                Q(platform__name__icontains=search_string),
            ]
            try:
                year_value = int(search_string)
            except ValueError:
                year_value = None
            if year_value:
                filters.append(Q(year_released=year_value))
            search_string_parts = search_string.split()
            if len(search_string_parts) == 1:
                if search_string.title() in Game.Status.labels:
                    search_status = Game.Status[search_string.upper()]
                    filters.append(Q(status=search_status))
            games = games.filter(build_dynamic_filter(filters, "|"))

    sort = apply_sort(games, parse_find_filter(request), GAME_SORTS, GAME_DEFAULT_SORT)
    games = sort.queryset
    for key in sort.unknown:
        messages.warning(request, f"Unknown sort field '{key}' was ignored.")

    games, page_obj, elided_page_range = paginate(request, games)

    data: TableData = {
        "header_action": Div(
            class_="flex justify-between",
        )[
            SearchField(search_string=search_string),
            A(href=reverse("games:add_game"))[StyledButton()["Add game"]],
        ],
        "columns": [
            Column("Name", "name"),
            Column("Sort Name", "sort_name"),
            Column("Year", "year"),
            Column("Status", "status"),
            Column("Wikidata", "wikidata"),
            Column("Created", "created"),
            Column("Actions", align="right"),
        ],
        "sort_terms": sort.terms,
        "rows": [
            make_row(
                NameWithIcon(game=game),
                PopoverTruncated(
                    game.sort_name
                    if game.sort_name is not None and game.name != game.sort_name
                    else "(identical)"
                ),
                str(game.year_released),
                GameStatusSelector(game, Game.Status.choices, get_token(request)),
                game.wikidata,
                local_strftime(game.created_at, dateformat),
                ButtonGroup(
                    [
                        {
                            "href": reverse("games:edit_game", args=[game.pk]),
                            "slot": Icon("edit"),
                            "color": "gray",
                        },
                        {
                            "href": reverse("games:delete_game", args=[game.pk]),
                            "slot": Icon("delete"),
                            "color": "red",
                        },
                    ]
                ),
            )
            for game in games
        ],
    }
    content = paginated_table_content(
        data,
        page_obj=page_obj,
        elided_page_range=elided_page_range,
        request=request,
    )
    # Prepend the filter bar above the table
    filter_bar = FilterBar(
        filter_json=filter_json,
        preset_list_url=reverse("games:list_presets"),
        preset_save_url=reverse("games:save_preset"),
    )
    content = Fragment(filter_bar, content)
    return render_page(
        request,
        content,
        title="Manage games",
    )


@login_required
def add_game(request: HttpRequest) -> HttpResponse:
    form = GameForm(request.POST or None)
    if form.is_valid():
        game = form.save()
        if "submit_and_redirect" in request.POST:
            return HttpResponseRedirect(
                reverse("games:add_purchase_for_game", kwargs={"game_id": game.id})
            )
        elif "submit_and_create_session" in request.POST:
            return HttpResponseRedirect(
                reverse("games:add_session_for_game", kwargs={"game_id": game.id})
            )
        else:
            return redirect("games:list_games")

    return render_page(
        request,
        AddForm(
            form,
            request=request,
            additional_row=Fragment(
                StyledButton(
                    [],
                    "Submit & Create Purchase",
                    color="gray",
                    type="submit",
                    name="submit_and_redirect",
                ),
                StyledButton(
                    [],
                    "Submit & Create Session",
                    color="gray",
                    type="submit",
                    name="submit_and_create_session",
                ),
            ),
        ),
        title="Add New Game",
        scripts=ModuleScript("dist/elements/search-select.js")
        + ModuleScript("dist/add_game.js"),
    )


def _delete_game_confirmation_modal(
    game: Game,
    session_count: int,
    purchase_count: int,
    playevent_count: int,
    request: HttpRequest,
) -> Node:
    data_items = []
    if session_count:
        data_items.append(Li(children=[f"{session_count} session(s)"]))
    if purchase_count:
        data_items.append(Li(children=[f"{purchase_count} purchase(s)"]))
    if playevent_count:
        data_items.append(Li(children=[f"{playevent_count} play event(s)"]))
    if not (session_count or purchase_count or playevent_count):
        data_items.append(Li(children=["No associated data"]))

    form = Element(
        "form",
        attributes=[
            ("hx-post", reverse("games:delete_game", args=[game.id])),
            ("hx-replace-url", "true"),
            ("hx-target", "#main-container"),
            ("hx-select", "#main-container"),
            ("hx-swap", "outerHTML"),
        ],
        children=[
            CsrfInput(request),
            P(
                attributes=[
                    (
                        "class",
                        "dark:text-white text-center mt-3 text-sm text-gray-600 "
                        "dark:text-gray-400",
                    )
                ],
                children=[
                    "This will permanently delete this game and all associated data:"
                ],
            ),
            Ul(
                attributes=[
                    (
                        "class",
                        "dark:text-white text-center mt-1 text-sm text-gray-600 "
                        "dark:text-gray-400 list-disc list-inside",
                    )
                ],
                children=data_items,
            ),
            P(
                attributes=[
                    (
                        "class",
                        "dark:text-white text-center mt-3 text-sm font-medium "
                        "text-red-600 dark:text-red-400",
                    )
                ],
                children=["This action cannot be undone."],
            ),
            Div(
                [("class", "items-center mt-5")],
                [
                    StyledButton(
                        [("class", "w-full")],
                        "Delete",
                        color="red",
                        size="lg",
                        type="submit",
                    ),
                    StyledButton(
                        [("class", "mt-0 w-full")],
                        "Cancel",
                        color="gray",
                        size="base",
                        onclick=(
                            "this.closest('#delete-game-confirmation-modal').remove()"
                        ),
                    ),
                ],
            ),
        ],
    )
    return Modal(
        "delete-game-confirmation-modal",
        children=[
            P(
                attributes=[
                    (
                        "class",
                        "text-2xl leading-6 font-medium dark:text-white text-center",
                    )
                ],
                children=["Delete Game"],
            ),
            P(
                attributes=[("class", "dark:text-white text-center mt-5")],
                children=[
                    "Are you sure you want to delete ",
                    Strong(children=[game.name]),
                    "?",
                ],
            ),
            form,
        ],
    )


@login_required
def delete_game_confirmation(request: HttpRequest, game_id: int) -> HttpResponse:
    game = get_object_or_404(Game, id=game_id)
    return HttpResponse(
        str(
            _delete_game_confirmation_modal(
                game,
                game.sessions.count(),
                game.purchases.count(),
                game.playevents.count(),
                request,
            )
        )
    )


@login_required
def delete_game(request: HttpRequest, game_id: int) -> HttpResponse:
    game = get_object_or_404(Game, id=game_id)
    game.delete()
    return redirect("games:list_sessions")


@login_required
@use_custom_redirect
def edit_game(request: HttpRequest, game_id: int) -> HttpResponse:
    purchase = get_object_or_404(Game, id=game_id)
    form = GameForm(request.POST or None, instance=purchase)
    if form.is_valid():
        form.save()
        return redirect("games:list_sessions")
    return render_page(
        request,
        AddForm(form, request=request),
        title="Edit Game",
        scripts=ModuleScript("dist/elements/search-select.js"),
    )


# --- view_game content builders -------------------------------------------

_STAT_SVGS = {
    "hours": '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="size-6"><path stroke-linecap="round" stroke-linejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" /></svg>',
    "sessions": '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="size-6"><path stroke-linecap="round" stroke-linejoin="round" d="M5.25 8.25h15m-16.5 7.5h15m-1.8-13.5-3.9 19.5m-2.1-19.5-3.9 19.5" /></svg>',
    "average": '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="size-6"><path stroke-linecap="round" stroke-linejoin="round" d="M7.5 14.25v2.25m3-4.5v4.5m3-6.75v6.75m3-9v9M6 20.25h12A2.25 2.25 0 0 0 20.25 18V6A2.25 2.25 0 0 0 18 3.75H6A2.25 2.25 0 0 0 3.75 6v12A2.25 2.25 0 0 0 6 20.25Z" /></svg>',
    "playrange": '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="size-6"><path stroke-linecap="round" stroke-linejoin="round" d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 0 1 2.25-2.25h13.5A2.25 2.25 0 0 1 21 7.5v11.25m-18 0A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75m-18 0v-7.5A2.25 2.25 0 0 1 5.25 9h13.5A2.25 2.25 0 0 1 21 11.25v7.5m-9-6h.008v.008H12v-.008ZM12 15h.008v.008H12V15Zm0 2.25h.008v.008H12v-.008ZM9.75 15h.008v.008H9.75V15Zm0 2.25h.008v.008H9.75v-.008ZM7.5 15h.008v.008H7.5V15Zm0 2.25h.008v.008H7.5v-.008Zm6.75-4.5h.008v.008h-.008v-.008Zm0 2.25h.008v.008h-.008V15Zm0 2.25h.008v.008h-.008v-.008Zm2.25-4.5h.008v.008H16.5v-.008Zm0 2.25h.008v.008H16.5V15Z" /></svg>',
}


def _played_row(game: Game, request: HttpRequest) -> Node:
    """'Played N times' split button: a generic outlined Dropdown wrapped in
    <play-event-row>, which owns only the 'Played +1' action."""
    from common.components import (
        DropdownActionItem,
        DropdownLinkItem,
        SplitButtonDropdown,
    )
    from common.components.custom_elements import DROPDOWN_TOGGLE_OUTLINE, _PlayEventRow
    from common.components.primitives import Button

    played = game.playevents.count()

    count_button = A(href=reverse("games:add_playevent"))[
        Button(class_=DROPDOWN_TOGGLE_OUTLINE + " rounded-s-lg")[
            Span(data_count="")[str(played)], " times"
        ]
    ]
    dropdown = SplitButtonDropdown(
        primary=count_button,
        id=f"played-{game.id}",
        aria_label="Playthrough actions",
        items=[
            DropdownLinkItem(
                reverse("games:add_playevent_for_game", args=[game.id]),
                "Add playthrough...",
            ),
            DropdownActionItem(
                "Played times +1",
                attributes=[("data-add-play", "")],
            ),
        ],
    )
    return _PlayEventRow(
        game_id=game.id,
        csrf=get_token(request),
        api_create_url=reverse("api-1.0.0:create_playevent"),
    )[
        Div(class_="flex gap-2 items-center")[
            Span(class_="uppercase")["Played"], dropdown
        ]
    ]


def _stat_popover(popover_id: str, tooltip: str, svg_key: str, value: str) -> Node:
    return Popover(
        popover_content=tooltip,
        wrapped_classes="flex gap-2 items-center",
        id=popover_id,
        children=[Safe(_STAT_SVGS[svg_key]), str(value)],
    )


def _meta_row(label: str, value: Node | str, extra: Node | str = "") -> Node:
    children: list[Node | str] = [
        Span(attributes=[("class", "uppercase")], children=[label]),
        value,
    ]
    if extra:
        children.append(extra)
    return Div([("class", "flex gap-2 items-center")], children)


def _game_action_buttons(game: Game) -> Node:
    # A segmented button group, same component as the table Actions cells. The
    # group owns position-based rounding and hover styling; margin is ours.
    return Div(class_="mb-3")[
        ButtonGroup(
            [
                {
                    "href": reverse(
                        "games:add_session_for_game", kwargs={"game_id": game.id}
                    ),
                    "slot": Span(class_="inline-flex items-center gap-1")[
                        Icon("play"), "Log this game"
                    ],
                    "color": "green",
                },
                {
                    "href": reverse("games:edit_game", args=[game.id]),
                    "slot": "Edit",
                    "color": "gray",
                },
                {
                    "href": "#",
                    "slot": "Delete",
                    "color": "red",
                    "hx_get": reverse("games:delete_game_confirmation", args=[game.id]),
                    "hx_target": "#global-modal-container",
                },
            ],
            size="md",
        )
    ]


def _game_history(statuschanges: QuerySet[GameStatusChange]) -> Node:
    items = []
    for change in statuschanges:
        if change.timestamp:
            prefix = f"{date_filter(change.timestamp, 'd/m/Y H:i')}: Changed"
        else:
            prefix = "At some point changed"
        old_status = GameStatus(
            status=change.old_status or "u",
            children=[change.get_old_status_display() if change.old_status else "-"],
        )
        new_status = GameStatus(
            status=change.new_status,
            children=[change.get_new_status_display()],
        )
        edit = A(
            href=reverse("games:edit_statuschange", args=[change.id]),
            children=["Edit"],
        )
        delete = A(
            href=reverse("games:delete_statuschange", args=[change.id]),
            children=["Delete"],
        )
        items.append(
            Li(
                attributes=[("class", "text-slate-500")],
                children=[
                    f"{prefix} status from",
                    old_status,
                    "to",
                    new_status,
                    "(",
                    edit,
                    ", ",
                    delete,
                    ")",
                ],
            )
        )
    return Ul(class_="list-disc list-inside", children=items)


def _game_section(
    title: str,
    count: int,
    table: Node,
    empty_message: str,
    view_all_url: str | None = None,
) -> Node:
    if view_all_url and count:
        view_all_link = A(
            href=view_all_url,
            children=[
                StyledButton(
                    icon=True,
                    color="gray",
                    size="xs",
                    title=f"View all {title.lower()} for this game",
                    children=[Icon("arrowright"), "View all"],
                )
            ],
        )
        header = Div(
            [("class", "flex items-center justify-between")],
            [H1(children=[title], badge=str(count) if count else ""), view_all_link],
        )
    else:
        header = H1(children=[title], badge=str(count) if count else "")
    return Div(
        [("class", "mb-6")],
        [
            header,
            table if count else empty_message,
        ],
    )


def _game_overview_metrics(game: Game) -> dict[str, Any]:
    """Request-free header metrics: total session count, play range, and the
    per-session average (excluding manually-logged sessions)."""
    sessions = game.sessions
    session_count = sessions.count()
    session_count_without_manual = sessions.without_manual().count()

    if sessions.exists():
        start = local_strftime(sessions.earliest().timestamp_start, "%b %Y")
        end = local_strftime(sessions.latest().timestamp_start, "%b %Y")
        playrange = start if start == end else f"{start} — {end}"
    else:
        playrange = "N/A"

    total_hours_without_manual = float(
        format_duration(sessions.calculated_duration_unformatted(), "%2.1H")
    )
    session_average_without_manual = round(
        safe_division(total_hours_without_manual, int(session_count_without_manual)), 1
    )
    return {
        "session_count": session_count,
        "playrange": playrange,
        "session_average_without_manual": session_average_without_manual,
    }


def _game_header(game: Game, request: HttpRequest, metrics: dict[str, Any]) -> Node:
    grey_value_class = "text-black dark:text-slate-300"
    title_span = Span(
        attributes=[("class", "text-balance max-w-120 text-4xl")],
        children=[
            Span(
                attributes=[("class", "font-bold font-serif")],
                children=[game.name],
            ),
        ]
        + (
            [
                Safe("&nbsp;"),
                Popover(
                    popover_content="Original release year",
                    wrapped_classes="text-slate-500 text-2xl",
                    id="popover-year",
                    children=[str(game.year_released)],
                ),
            ]
            if game.year_released
            else []
        ),
    )
    stats_row = Div(
        [("class", "flex gap-4 dark:text-slate-400 mb-3")],
        [
            _stat_popover(
                "popover-hours",
                "Total hours played",
                "hours",
                game.playtime_formatted(),
            ),
            _stat_popover(
                "popover-sessions",
                "Number of sessions",
                "sessions",
                metrics["session_count"],
            ),
            _stat_popover(
                "popover-average",
                "Average playtime per session",
                "average",
                metrics["session_average_without_manual"],
            ),
            _stat_popover(
                "popover-playrange",
                "Earliest and latest dates played",
                "playrange",
                metrics["playrange"],
            ),
        ],
    )
    metadata = Div(
        [("class", "flex flex-col mb-6 text-gray-600 dark:text-slate-400 gap-y-4")],
        [
            _meta_row(
                "Original year",
                Span(
                    attributes=[("class", grey_value_class)],
                    children=[str(game.original_year_released)],
                ),
            ),
            _meta_row(
                "Status",
                GameStatusSelector(game, Game.Status.choices, get_token(request)),
                "👑" if game.mastered else "",
            ),
            _played_row(game, request),
            _meta_row(
                "Platform",
                Span(
                    attributes=[("class", grey_value_class)],
                    children=[str(game.platform)],
                ),
            ),
        ],
    )
    return Div(
        [("id", "game-info"), ("class", "mb-10")],
        [
            Div([("class", "flex gap-5 mb-3")], [title_span]),
            stats_row,
            metadata,
            _game_action_buttons(game),
        ],
    )


def _purchases_section(game: Game) -> Node:
    purchases = game.purchases.order_by("date_purchased")
    rows = [
        make_row(
            LinkedPurchase(purchase),
            purchase.get_type_display(),
            purchase.date_purchased.strftime(dateformat),
            PurchasePrice(purchase),
            ButtonGroup(
                [
                    {
                        "href": reverse("games:edit_purchase", args=[purchase.pk]),
                        "slot": Icon("edit"),
                        "color": "gray",
                    },
                    {
                        "href": reverse("games:delete_purchase", args=[purchase.pk]),
                        "slot": Icon("delete"),
                        "color": "red",
                    },
                ]
            ),
        )
        for purchase in purchases
    ]
    table = StyledTable(
        columns=[
            Column("Name"),
            Column("Type"),
            Column("Date"),
            Column("Price"),
            Column("Actions", align="right"),
        ],
        rows=rows,
    )
    return _game_section(
        "Purchases",
        purchases.count(),
        table,
        "No purchases yet.",
        view_all_url=filter_url(PurchaseFilter.where(games=[game.id])),
    )


def _sessions_section(game: Game) -> Node:
    sessions = game.sessions.select_related("device").order_by("-timestamp_start")
    session_count = sessions.count()
    rows = [
        make_row(
            session_time_range(session),
            session.duration_formatted_with_mark(),
            session.device.name if session.device else "",
        )
        for session in sessions[:5]
    ]
    table = StyledTable(
        columns=[
            Column("Date"),
            Column("Duration"),
            Column("Device"),
        ],
        rows=rows,
    )
    return _game_section(
        "Sessions",
        session_count,
        table,
        "No sessions yet.",
        view_all_url=filter_url(SessionFilter.where(game=[game.id])),
    )


def _playevents_section(game: Game) -> Node:
    playevents = game.playevents.all()
    data = create_playevent_tabledata(playevents, exclude_columns=["Game"])
    table = StyledTable(columns=data["columns"], rows=data["rows"])
    section = _game_section(
        "Play Events",
        playevents.count(),
        table,
        "No play events yet.",
        view_all_url=filter_url(PlayEventFilter.where(game=[game.id])),
    )
    # Re-fetch this section (table + count badge) when the played-row "+1"
    # control records a play, so it updates without a full reload. Mirrors the
    # history section's status-changed refresh.
    return Div(
        [
            ("id", "playevents-container"),
            ("hx-get", ""),
            ("hx-trigger", "play-added from:body"),
            ("hx-select", "#playevents-container"),
            ("hx-swap", "outerHTML"),
        ],
        [section],
    )


def _history_section(game: Game) -> Node:
    statuschanges: QuerySet[GameStatusChange] = game.status_changes.all()
    count = statuschanges.count()
    return Div(
        class_="mb-6",
        id="history-container",
        hx_trigger="status-changed from:body",
        hx_select="#history-container",
        hx_swap="outerHTML",
    )[
        H1(children=["History"], badge=str(count) if count else ""),
        _game_history(statuschanges),
    ]


_GET_SESSION_COUNT_SCRIPT = Safe(
    "<script>\n"
    "            function getSessionCount() {\n"
    "                return document.getElementById('session-count')"
    '.textContent.match("[0-9]+");\n'
    "            }\n"
    "    </script>"
)


@login_required
def view_game(request: HttpRequest, game_id: int) -> HttpResponse:
    game = Game.objects.get(id=game_id)
    content = Div(
        [
            (
                "class",
                f"dark:text-white w-full {CONTENT_MAX_WIDTH_CLASS} self-center px-2",
            )
        ],
        [
            _game_header(game, request, _game_overview_metrics(game)),
            _purchases_section(game),
            _sessions_section(game),
            _playevents_section(game),
            _history_section(game),
            _GET_SESSION_COUNT_SCRIPT,
        ],
    )
    request.session["return_path"] = request.path
    return render_page(
        request,
        content,
        title=f"Game Overview - {game.name}",
        mastered=game.mastered,
    )
