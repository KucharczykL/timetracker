from typing import Any

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.middleware.csrf import get_token
from django.db.models import Q
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect
from django.template.defaultfilters import date as date_filter
from django.urls import reverse
from django.utils.safestring import SafeText, mark_safe

from common.components import (
    A,
    AddForm,
    Button,
    ButtonGroup,
    Component,
    CsrfInput,
    Div,
    FilterBar,
    GameStatus,
    GameStatusSelector,
    H1,
    Icon,
    SearchField,
    LinkedPurchase,
    Modal,
    ModuleScript,
    NameWithIcon,
    Popover,
    PopoverTruncated,
    PurchasePrice,
    SimpleTable,
    paginated_table_content,
)
from common.icons import get_icon
from common.layout import render_page
from common.time import (
    dateformat,
    format_duration,
    local_strftime,
    timeformat,
)
from common.utils import build_dynamic_filter, paginate, safe_division, truncate
from games.filters import parse_game_filter
from games.forms import GameForm
from games.models import Game
from games.views.general import use_custom_redirect
from games.views.playevent import create_playevent_tabledata


@login_required
def list_games(request: HttpRequest, search_string: str = "") -> HttpResponse:
    games = Game.objects.order_by("-created_at")

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

    games, page_obj, elided_page_range = paginate(request, games)

    data = {
        "header_action": Div(
            children=[
                SearchField(search_string=search_string),
                A([], Button([], "Add game"), url_name="games:add_game"),
            ],
            attributes=[("class", "flex justify-between")],
        ),
        "columns": [
            "Name",
            "Sort Name",
            "Year",
            "Status",
            "Wikidata",
            "Created",
            "Actions",
        ],
        "rows": [
            [
                NameWithIcon(game=game),
                PopoverTruncated(
                    game.sort_name
                    if game.sort_name is not None and game.name != game.sort_name
                    else "(identical)"
                ),
                game.year_released,
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
            ]
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
    content = mark_safe(str(filter_bar) + str(content))
    return render_page(
        request,
        content,
        title="Manage games",
        scripts=ModuleScript("range_slider.js")
        + ModuleScript("search_select.js")
        + ModuleScript("filter_bar.js"),
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
        else:
            return redirect("games:list_games")

    return render_page(
        request,
        AddForm(
            form,
            request=request,
            additional_row=Button(
                [],
                "Submit & Create Purchase",
                color="gray",
                type="submit",
                name="submit_and_redirect",
            ),
        ),
        title="Add New Game",
        scripts=ModuleScript("search_select.js") + ModuleScript("add_game.js"),
    )


def _delete_game_confirmation_modal(
    game: Game,
    session_count: int,
    purchase_count: int,
    playevent_count: int,
    request: HttpRequest,
) -> SafeText:
    data_items = []
    if session_count:
        data_items.append(
            Component(tag_name="li", children=[f"{session_count} session(s)"])
        )
    if purchase_count:
        data_items.append(
            Component(tag_name="li", children=[f"{purchase_count} purchase(s)"])
        )
    if playevent_count:
        data_items.append(
            Component(tag_name="li", children=[f"{playevent_count} play event(s)"])
        )
    if not (session_count or purchase_count or playevent_count):
        data_items.append(Component(tag_name="li", children=["No associated data"]))

    form = Component(
        tag_name="form",
        attributes=[
            ("hx-post", reverse("games:delete_game", args=[game.id])),
            ("hx-replace-url", "true"),
            ("hx-target", "#main-container"),
            ("hx-select", "#main-container"),
            ("hx-swap", "outerHTML"),
        ],
        children=[
            CsrfInput(request),
            Component(
                tag_name="p",
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
            Component(
                tag_name="ul",
                attributes=[
                    (
                        "class",
                        "dark:text-white text-center mt-1 text-sm text-gray-600 "
                        "dark:text-gray-400 list-disc list-inside",
                    )
                ],
                children=data_items,
            ),
            Component(
                tag_name="p",
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
                    Button(
                        [("class", "w-full")],
                        "Delete",
                        color="red",
                        size="lg",
                        type="submit",
                    ),
                    Button(
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
            Component(
                tag_name="h1",
                attributes=[
                    (
                        "class",
                        "text-2xl leading-6 font-medium dark:text-white text-center",
                    )
                ],
                children=["Delete Game"],
            ),
            Component(
                tag_name="p",
                attributes=[("class", "dark:text-white text-center mt-5")],
                children=[
                    "Are you sure you want to delete ",
                    Component(tag_name="strong", children=[game.name]),
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
        _delete_game_confirmation_modal(
            game,
            game.sessions.count(),
            game.purchases.count(),
            game.playevents.count(),
            request,
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
        scripts=ModuleScript("search_select.js"),
    )


# --- view_game content builders -------------------------------------------

_STAT_SVGS = {
    "hours": '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="size-6"><path stroke-linecap="round" stroke-linejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" /></svg>',
    "sessions": '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="size-6"><path stroke-linecap="round" stroke-linejoin="round" d="M5.25 8.25h15m-16.5 7.5h15m-1.8-13.5-3.9 19.5m-2.1-19.5-3.9 19.5" /></svg>',
    "average": '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="size-6"><path stroke-linecap="round" stroke-linejoin="round" d="M7.5 14.25v2.25m3-4.5v4.5m3-6.75v6.75m3-9v9M6 20.25h12A2.25 2.25 0 0 0 20.25 18V6A2.25 2.25 0 0 0 18 3.75H6A2.25 2.25 0 0 0 3.75 6v12A2.25 2.25 0 0 0 6 20.25Z" /></svg>',
    "playrange": '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="size-6"><path stroke-linecap="round" stroke-linejoin="round" d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 0 1 2.25-2.25h13.5A2.25 2.25 0 0 1 21 7.5v11.25m-18 0A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75m-18 0v-7.5A2.25 2.25 0 0 1 5.25 9h13.5A2.25 2.25 0 0 1 21 11.25v7.5m-9-6h.008v.008H12v-.008ZM12 15h.008v.008H12V15Zm0 2.25h.008v.008H12v-.008ZM9.75 15h.008v.008H9.75V15Zm0 2.25h.008v.008H9.75v-.008ZM7.5 15h.008v.008H7.5V15Zm0 2.25h.008v.008H7.5v-.008Zm6.75-4.5h.008v.008h-.008v-.008Zm0 2.25h.008v.008h-.008V15Zm0 2.25h.008v.008h-.008v-.008Zm2.25-4.5h.008v.008H16.5v-.008Zm0 2.25h.008v.008H16.5V15Z" /></svg>',
}

_PLAYED_ROW_TEMPLATE = """<div class="flex gap-2 items-center" x-data="{ open: false }">
    <span class="uppercase">Played</span>
    <div class="inline-flex rounded-md shadow-2xs" role="group" x-data="{ played: @@PLAYED_COUNT@@ }">
        <a href="@@ADD_PE@@">
        <button type="button" class="px-4 py-2 text-sm font-medium text-gray-900 bg-white border border-gray-200 rounded-s-lg hover:bg-gray-100 hover:text-blue-700 focus:z-10 focus:ring-2 focus:ring-blue-700 focus:text-blue-700 dark:bg-gray-800 dark:border-gray-700 dark:text-white dark:hover:text-white dark:hover:bg-gray-700 dark:focus:ring-blue-500 dark:focus:text-white hover:cursor-pointer">
            <span x-text="played"></span> times
        </button>
        </a>
        <button type="button" x-on:click="open = !open" @click.outside="open = false" class="relative px-4 py-2 text-sm font-medium text-gray-900 bg-white border-e border-b border-t border-gray-200 rounded-e-lg hover:bg-gray-100 hover:text-blue-700 focus:z-10 focus:ring-2 focus:ring-blue-700 focus:text-blue-700 dark:bg-gray-800 dark:border-gray-700 dark:text-white dark:hover:text-white dark:hover:bg-gray-700 dark:focus:ring-blue-500 dark:focus:text-white align-middle hover:cursor-pointer">
            @@ARROWDOWN@@
            <div
                class="absolute top-full -left-px w-auto whitespace-nowrap z-10 text-sm font-medium bg-gray-800/20 backdrop-blur-lg rounded-md rounded-tl-none border border-gray-200 dark:border-gray-700"
                x-show="open"
            >
                <ul
                    class=""
                >
                    <li class="px-4 py-2 dark:hover:text-white dark:hover:bg-gray-700 dark:focus:ring-blue-500 dark:focus:text-white rounded-tr-md">
                        <a href="@@ADD_PE_FOR_GAME@@">Add playthrough...</a>
                    </li>
                    <li
                        x-on:click="createPlayEvent"
                        class="relative px-4 py-2 dark:hover:text-white dark:hover:bg-gray-700 dark:focus:ring-blue-500 dark:focus:text-white rounded-b-md"
                    >
                        Played times +1
                    </li>
                    <script>
                       function createPlayEvent() {
                        this.played++;
                        // TODO: migrate to hx-post + hx-on::after-request for HTMX-native toast handling
                        fetchWithHtmxTriggers('@@API_CREATE@@', {
                            method: 'POST',
                            headers: { 'X-CSRFToken': '@@CSRF@@', 'Content-Type': 'application/json' },
                            body: '{"game_id": @@GAME_ID@@}'
                        })
                        .catch(() => {
                            this.played--;
                            console.error('Failed to record play');
                        });
                       }
                    </script>
                </ul>
            </div>
        </button>
      </div>
</div>"""


def _played_row(game: Game, request: HttpRequest) -> SafeText:
    """The 'Played N times' control with its Alpine.js dropdown."""
    replacements = {
        "@@PLAYED_COUNT@@": str(game.playevents.count()),
        "@@ADD_PE@@": reverse("games:add_playevent"),
        "@@ARROWDOWN@@": get_icon("arrowdown"),
        "@@ADD_PE_FOR_GAME@@": reverse("games:add_playevent_for_game", args=[game.id]),
        "@@API_CREATE@@": reverse("api-1.0.0:create_playevent"),
        "@@CSRF@@": get_token(request),
        "@@GAME_ID@@": str(game.id),
    }
    html = _PLAYED_ROW_TEMPLATE
    for token, value in replacements.items():
        html = html.replace(token, value)
    return mark_safe(html)


def _stat_popover(popover_id: str, tooltip: str, svg_key: str, value: str) -> SafeText:
    return Popover(
        popover_content=tooltip,
        wrapped_classes="flex gap-2 items-center",
        id=popover_id,
        children=[mark_safe(_STAT_SVGS[svg_key]), str(value)],
    )


def _meta_row(
    label: str, value: SafeText | str, extra: SafeText | str = ""
) -> SafeText:
    children: list[SafeText | str] = [
        Component(
            tag_name="span", attributes=[("class", "uppercase")], children=[label]
        ),
        value,
    ]
    if extra:
        children.append(extra)
    return Div([("class", "flex gap-2 items-center")], children)


def _game_action_buttons(game: Game) -> SafeText:
    edit_class = (
        "px-4 py-2 text-sm font-medium text-gray-900 bg-white border border-gray-200 "
        "rounded-s-lg hover:bg-gray-100 hover:text-blue-700 focus:z-10 focus:ring-2 "
        "focus:ring-blue-700 focus:text-blue-700 dark:bg-gray-800 dark:border-gray-700 "
        "dark:text-white dark:hover:text-white dark:hover:bg-gray-700 "
        "dark:focus:ring-blue-500 dark:focus:text-white hover:cursor-pointer"
    )
    delete_class = (
        "px-4 py-2 text-sm font-medium text-gray-900 bg-white border border-gray-200 "
        "rounded-e-lg hover:bg-red-100 hover:text-blue-700 focus:z-10 focus:ring-2 "
        "focus:ring-blue-700 focus:text-blue-700 dark:bg-gray-800 dark:border-gray-700 "
        "dark:text-white dark:hover:text-white dark:hover:bg-red-700 "
        "dark:focus:ring-blue-500 dark:focus:text-white hover:cursor-pointer"
    )
    edit_link = Component(
        tag_name="a",
        attributes=[("href", reverse("games:edit_game", args=[game.id]))],
        children=[
            Component(
                tag_name="button",
                attributes=[("type", "button"), ("class", edit_class)],
                children=["Edit"],
            )
        ],
    )
    delete_link = Component(
        tag_name="a",
        attributes=[
            ("href", "#"),
            ("hx-get", reverse("games:delete_game_confirmation", args=[game.id])),
            ("hx-target", "#global-modal-container"),
        ],
        children=[
            Component(
                tag_name="button",
                attributes=[("type", "button"), ("class", delete_class)],
                children=["Delete"],
            )
        ],
    )
    return Div(
        [("class", "inline-flex rounded-md shadow-xs mb-3"), ("role", "group")],
        [edit_link, delete_link],
    )


def _game_history(statuschanges) -> SafeText:
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
        edit = Component(
            tag_name="a",
            attributes=[("href", reverse("games:edit_statuschange", args=[change.id]))],
            children=["Edit"],
        )
        delete = Component(
            tag_name="a",
            attributes=[
                ("href", reverse("games:delete_statuschange", args=[change.id]))
            ],
            children=["Delete"],
        )
        items.append(
            Component(
                tag_name="li",
                attributes=[("class", "text-slate-500")],
                children=[
                    f"{prefix} status from ",
                    old_status,
                    " to ",
                    new_status,
                    " (",
                    edit,
                    ", ",
                    delete,
                    ")",
                ],
            )
        )
    return Component(
        tag_name="ul",
        attributes=[("class", "list-disc list-inside")],
        children=items,
    )


def _game_section(
    title: str, count: int, table: SafeText, empty_message: str
) -> SafeText:
    return Div(
        [("class", "mb-6")],
        [
            H1(children=[title], badge=count),
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


def _game_header(game: Game, request: HttpRequest, metrics: dict[str, Any]) -> SafeText:
    grey_value_class = "text-black dark:text-slate-300"
    title_span = Component(
        tag_name="span",
        attributes=[("class", "text-balance max-w-120 text-4xl")],
        children=[
            Component(
                tag_name="span",
                attributes=[("class", "font-bold font-serif")],
                children=[game.name],
            ),
        ]
        + (
            [
                mark_safe("&nbsp;"),
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
                Component(
                    tag_name="span",
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
                Component(
                    tag_name="span",
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


def _purchases_section(game: Game) -> SafeText:
    purchases = game.purchases.order_by("date_purchased")
    rows = [
        [
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
        ]
        for purchase in purchases
    ]
    table = SimpleTable(columns=["Name", "Type", "Date", "Price", "Actions"], rows=rows)
    return _game_section("Purchases", purchases.count(), table, "No purchases yet.")


def _sessions_section(game: Game, request: HttpRequest) -> SafeText:
    sessions_all = game.sessions.order_by("-timestamp_start")
    session_count = sessions_all.count()
    last_session = sessions_all.latest() if sessions_all.exists() else None

    page_number = request.GET.get("page", 1)
    page_obj = Paginator(sessions_all, 5).get_page(page_number)
    elided_page_range = (
        page_obj.paginator.get_elided_page_range(page_number, on_each_side=1, on_ends=1)
        if session_count > 5
        else None
    )

    header_action = Div(
        children=[
            A(
                url_name="games:add_session",
                children=Button(icon=True, size="xs", children=[Icon("play"), "LOG"]),
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
        ],
    )
    rows = [
        [
            NameWithIcon(session=session),
            f"{local_strftime(session.timestamp_start)}{f' — {local_strftime(session.timestamp_end, timeformat)}' if session.timestamp_end else ''}",
            session.duration_formatted_with_mark(),
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
                        "href": reverse("games:edit_session", args=[session.pk]),
                        "slot": Icon("edit"),
                        "color": "gray",
                    },
                    {
                        "href": reverse("games:delete_session", args=[session.pk]),
                        "slot": Icon("delete"),
                        "color": "red",
                    },
                ]
            ),
        ]
        for session in page_obj.object_list
    ]
    table = SimpleTable(
        columns=["Game", "Date", "Duration", "Actions"],
        rows=rows,
        header_action=header_action,
        page_obj=page_obj,
        elided_page_range=elided_page_range,
        request=request,
    )
    return _game_section("Sessions", session_count, table, "No sessions yet.")


def _playevents_section(game: Game) -> SafeText:
    playevents = game.playevents.all()
    data = create_playevent_tabledata(playevents, exclude_columns=["Game"])
    table = SimpleTable(columns=data["columns"], rows=data["rows"])
    return _game_section(
        "Play Events", playevents.count(), table, "No play events yet."
    )


def _history_section(game: Game) -> SafeText:
    statuschanges = game.status_changes.all()
    return Div(
        [
            ("class", "mb-6"),
            ("id", "history-container"),
            ("hx-get", ""),
            ("hx-trigger", "status-changed from:body"),
            ("hx-select", "#history-container"),
            ("hx-swap", "outerHTML"),
        ],
        [
            H1(children=["History"], badge=statuschanges.count()),
            _game_history(statuschanges),
        ],
    )


_GET_SESSION_COUNT_SCRIPT = mark_safe(
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
        [("class", "dark:text-white max-w-sm sm:max-w-xl lg:max-w-3xl mx-auto")],
        [
            _game_header(game, request, _game_overview_metrics(game)),
            _purchases_section(game),
            _sessions_section(game, request),
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
