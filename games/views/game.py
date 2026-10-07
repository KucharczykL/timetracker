import logging
from collections.abc import Sequence
from datetime import timedelta
from functools import partial
from typing import Any, NamedTuple, NoReturn, cast
from uuid import UUID

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import Count, F, Max, Min, Sum
from django.http import Http404, HttpRequest, HttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from common.components import (
    ICON_BUTTON_SIZE_CLASS,
    AccessBadge,
    AddForm,
    ButtonGroup,
    Cell,
    Chip,
    Column,
    ControlButton,
    Div,
    Duration,
    DurationAlternates,
    DurationText,
    ExternalReferenceLinks,
    FormFields,
    Fragment,
    GamesTabs,
    GameStatus,
    GameStatusSelector,
    Icon,
    Link,
    NameWithIcon,
    Node,
    P,
    PageHeading,
    PlaytimeHalves,
    Popover,
    QuickFilterBar,
    SelectionDeclaration,
    StyledTable,
    SummaryGroup,
    SummaryList,
    SummaryRow,
    TableData,
    Ul,
    drop_columns,
    make_row,
    paginated_table_content,
    parse_filter_dict,
)
from common.components.field_mirror import FieldMirror
from common.components.game_addon import GameAddon
from common.components.primitives import (
    SECTION_SURFACE_CLASS,
    Li,
    Span,
    custom_element_builder,
)
from common.date_time_presentation import (
    DateTimePresentation,
    date_time_presentation_for_request,
)
from common.duration_presentation import (
    DurationPresentation,
    duration_presentation_for_request,
)
from common.filter_execution import execute_filter, regex_timeout_view
from common.form_dialog import CreatedRedirect
from common.layout import render_page
from common.returns import LinkFacts, OriginUrl, action_url
from common.temporal_presentation import (
    UNKNOWN_TEXT,
    TemporalText,
    present_temporal_value,
)
from common.utils import paginate, safe_division
from games.bulk_game_edit import EDIT as EDIT_GAMES
from games.bulk_playthrough_acts import COMPLETE_RUNS, START_RUNS
from games.bulk_removal import REMOVE_GAME, REMOVE_RECORD, REMOVE_RUN
from games.bulk_tray import tray_actions
from games.catalog_addons import FOREIGN_PARENT_LABEL, foreign_to
from games.catalog_form import CatalogGraphForm
from games.catalog_release import SHARED_GAME_RELEASE
from games.catalog_submit import submitted_game_or_form_error
from games.external_references import CatalogTarget, external_reference_url_or_none
from games.filters import (
    FindFilter,
    GameFilter,
    HistoricalPlaytimeFilter,
    LibraryEntryFilter,
    NarrowingClauses,
    PlayerSessionFilter,
    PlaythroughFilter,
    filter_query_context_for_library,
    filter_url,
    parse_game_filter,
)
from games.formatting import session_time_range
from games.forms import GAME_FORM_GROUPS, GameForm, game_option
from games.list_columns import column_choice
from games.models import (
    Edition,
    EditionKind,
    ExternalReference,
    Game,
    GameKind,
    PlayerGameStatus,
    PlayerSessionQuerySet,
    PlayerSessionTimingMode,
    Playthrough,
    Release,
    UserLibrary,
)
from games.ownership import owned_or_404
from games.reads.catalog_hierarchy import (
    EditionEntry,
    game_hierarchy,
    tracked_addons,
)
from games.reads.entries import AccessSummary, access_summaries
from games.reads.external_references import ReferenceMap, held_by, references_for
from games.reads.game_departures import game_departures
from games.reads.games_list import games_list_base
from games.reads.historical_playtime_page import run_labels_for
from games.reads.historical_playtime_records import RECORD_ORDER, listed_records
from games.reads.player_sessions import GAME, shown_sessions
from games.reads.playergame_history import StatusEntry, status_history
from games.reads.playthrough_activity import ActivityClock, activity_clock
from games.reads.playthrough_completions import GAME_RUNS, reported_completion_day
from games.reads.playthrough_numbering import numbered_for
from games.reads.playthrough_runs import tracked_game
from games.reads.playtime import (
    game_playtime,
    playtime_matching_both,
    playtime_sort_key,
)
from games.reads.previous_copies import (
    previous_copies_filter,
    previous_copy_purchases_filter,
    refunded_held_purchases_filter,
)
from games.reads.releases import UNSPECIFIED_PLATFORM
from games.reads.sums import PlaytimeBreakdown
from games.reference_form import ReferenceSetForm
from games.sorting import (
    GAME_DEFAULT_SORT,
    GAME_SORTS,
    SortResult,
    apply_sort,
    parse_find_filter,
)
from games.views.catalog_section import editions_area
from games.views.filtering import (
    apply_structured_filter,
    builder_url_for,
    warn_unknown_sort,
)
from games.views.game_menu import game_row_menu
from games.views.historical_playtime import (
    historical_playtime_tabledata,
)
from games.views.library_cards import (
    EMPTY_LIBRARY,
    EMPTY_LIBRARY_NOW,
    CopyRows,
    copy_rows,
    library_add_control,
)
from games.views.playergame_writes import (
    record_facts_for_request,
    remove_game_for_request,
    restore_game_for_request,
    track_game_for_request,
)
from games.views.playthrough_rows import playthrough_tabledata
from games.views.reference_section import references_area
from games.views.removal import confirm_and_remove, restore_and_return
from games.views.returns import origin_from, return_url
from games.writes.playergame import new_correlation_id

logger = logging.getLogger("games")

#: The value half of a meta row.
META_VALUE_CLASS = "text-heading"
#: Lets a grid cell shrink below its content.
_GRID_CELL_CLASS = "min-w-0"
#: Formatted with `count`.
ADDONS_STAY = "{count} add-on(s) stay, off the Games list"
#: Said on the page, because the shape is not final.
EDITIONS_UNDER_CONSTRUCTION = (
    "Under construction. These are catalog facts only. A session cannot name "
    "an edition yet, so no playtime is shown here and this layout will change. "
    "A platform beyond the first one does not reach the games list yet."
)

_RefreshingSection = custom_element_builder("refreshing-section")


def _access_cell(
    game_id: UUID,
    summary: AccessSummary | None,
    presentation: DateTimePresentation,
) -> Cell:
    """No badge without a live copy."""
    if summary is None:
        return ""
    return AccessBadge(summary, presentation, id=f"access-{game_id}")


def _wikidata_cell(provider_key: str) -> Cell:
    """The mirror column, linked where it links."""
    if not provider_key:
        return ""
    url = external_reference_url_or_none(
        provider="wikidata", entity_kind="game", provider_key=provider_key
    )
    return Link(href=url)[provider_key] if url is not None else provider_key


type ColumnLabel = str  # e.g. "Playtime"


class GameList(NamedTuple):
    sort: SortResult
    #: Names what the Playtime column sums.
    playtime_label: ColumnLabel


def games_for_list(
    library: UserLibrary, *, game_filter: GameFilter | None, find: FindFilter
) -> GameList:
    """The list's queryset: filtered, annotated, sorted, unpaged.

    One function, so the benchmark times the plan the page serves.
    """
    games = games_list_base(library, game_filter).select_related("platform")
    #: Narrows the Playtime column; none counts all.
    clauses = NarrowingClauses(None, None)
    if game_filter is not None:
        context = filter_query_context_for_library(library)
        games = execute_filter(game_filter, games, context)
        clauses = game_filter.narrowing()
    playtime_label = "Playtime"
    if clauses.sessions is None and clauses.records is None:
        #: The sort reuses the column's subqueries.
        games = games.annotate(filtered_playtime=playtime_sort_key(library)).alias(
            total_playtime=F("filtered_playtime")
        )
    else:
        playtime_label = (
            "Playtime (matching sessions)"
            if clauses.records is None
            else "Playtime (matching)"
        )
        #: An alias: only `?sort=playtime` reads it.
        games = games.alias(total_playtime=playtime_sort_key(library)).annotate(
            filtered_playtime=playtime_matching_both(
                library, clauses.sessions, clauses.records
            )
        )
    #: No column renders it; `?sort=finished` reads it.
    games = games.annotate(completed_day=reported_completion_day(library, GAME_RUNS))
    return GameList(
        apply_sort(games, find, GAME_SORTS, GAME_DEFAULT_SORT), playtime_label
    )


def game_list_columns(playtime_label: str) -> list[Column]:
    """The columns of the list. The filter selects the playtime label."""
    return [
        Column("Name", "name", shrinkable=True, key="name", hideable=False),
        Column("Year", "year", priority=2, key="year"),
        Column(playtime_label, "filtered_playtime", priority=2, key="playtime"),
        Column("Status", "status", priority=3, key="status"),
        Column("Kind", "kind", key="kind", hidden_by_default=True),
        Column("Access", key="access", hidden_by_default=True),
        Column("Wikidata", "wikidata", key="wikidata", hidden_by_default=True),
        Column("Created", "created", key="created", hidden_by_default=True),
        Column(
            "Unfinished lists",
            "unfinished_lists",
            key="unfinished_lists",
            hidden_by_default=True,
        ),
        Column(
            "Dropped figures",
            "dropped_figures",
            key="dropped_figures",
            hidden_by_default=True,
        ),
    ]


@login_required
@regex_timeout_view
def list_games(request: HttpRequest) -> HttpResponse:
    library = cast(User, request.user).library
    presentation = date_time_presentation_for_request(request)
    durations = duration_presentation_for_request(request)
    origin = request.get_full_path()

    # ── Structured filter (Stash-style JSON; free-text search lives here too) ──
    filter_json = request.GET.get("filter", "")
    game_filter: GameFilter | None = None
    if filter_json:
        game_filter = apply_structured_filter(request, parse_game_filter, filter_json)

    find = parse_find_filter(request)
    listed = games_for_list(library, game_filter=game_filter, find=find)
    sort = listed.sort
    warn_unknown_sort(request, sort.unknown, entity="game")

    games, page_obj, elided_page_range = paginate(sort.queryset, find)

    columns = game_list_columns(listed.playtime_label)
    hidden, picker = column_choice(request, "games", columns)
    csrf_token = get_token(request)
    page_games = list(games)
    summaries = (
        {}
        if "access" in hidden
        else access_summaries(library, [game.pk for game in page_games])
    )
    kept_columns, kept_cells = drop_columns(
        columns,
        [
            [
                NameWithIcon(game=game, include_sort_name=True),
                str(game.year_released),
                Duration(
                    game.filtered_playtime or timedelta(0),
                    durations,
                    id_scope=f"game-{game.pk}-playtime",
                ),
                GameStatusSelector(
                    game,
                    PlayerGameStatus.choices,
                    csrf_token,
                    current=game.tracked_status,
                ),
                GameKind(game.kind).label,
                _access_cell(game.pk, summaries.get(game.pk), presentation),
                _wikidata_cell(game.wikidata),
                presentation.format(game.created_at, "date"),
                "Excluded" if game.tracked_excluded_from_unfinished else "",
                "Excluded" if game.tracked_excluded_from_dropped else "",
            ]
            for game in page_games
        ],
        hidden,
    )
    data: TableData = {
        "caption": "Games",
        "columns": kept_columns,
        #: Every row carries its acts in the slot, rendered or not.
        "menu_slot": True,
        "sort_terms": sort.terms,
        "rows": [
            make_row(*cells, key=str(game.pk), menu=game_row_menu(game, origin))
            for game, cells in zip(page_games, kept_cells, strict=True)
        ],
        "column_picker": picker,
        "selection": {
            "filter": filter_json,
            "csrf_token": csrf_token,
            "actions": tray_actions(EDIT_GAMES.name, REMOVE_GAME.name, origin=origin),
        },
    }
    content = paginated_table_content(
        data,
        page_obj=page_obj,
        elided_page_range=elided_page_range,
        request=request,
        page_size=find.per_page,
    )
    # The quick bar is the page's only filter tier: dropdown facets,
    # preset picker, and the builder entry point in the action group.
    builder_url = builder_url_for(
        "games", filter_json, find.sort, find.per_page_override
    )
    parsed_filter = parse_filter_dict(filter_json, GameFilter)
    quick_bar = QuickFilterBar(
        presentation=presentation,
        mode="games",
        existing=parsed_filter,
        builder_url=builder_url,
        preset_api_url=reverse("api-1.0.0:list_presets"),
        per_page_override=find.per_page_override,
    )
    content = Div()[GamesTabs("games"), quick_bar, content]
    return render_page(
        request,
        content,
        title="Manage games",
        width="full",
    )


@login_required
def add_game(request: HttpRequest) -> HttpResponse:
    library = cast(User, request.user).library
    presentation = date_time_presentation_for_request(request)
    form = GameForm(
        request.POST or None,
        library=library,
        presentation=presentation,
        facts=request.GET,
    )
    graph = CatalogGraphForm(
        request.POST or None, game=None, library=library, presentation=presentation
    )
    references = ReferenceSetForm(request.POST or None, target=None, library=library)
    #: Both read, whatever either says. `and` stops at the first false
    #: one, and a graph the Game's own refusal never reached states no
    #: sentence of its own and lets no mark fall.
    game_reads = form.is_valid()
    references_read = references.is_valid()
    if graph.is_valid() and game_reads and references_read:
        game = submitted_game_or_form_error(form, graph, references)
        if game is not None:
            correlation_id = new_correlation_id()
            if not track_game_for_request(request, game, correlation_id=correlation_id):
                #: Nothing tracks it, so no read reaches it: the list
                #: joins the projection and the detail page answers
                #: 404, while the name goes on holding the unique
                #: constraint against a second attempt. Undo the
                #: insert rather than leave a row only the database
                #: can see. No event names it, so this really deletes.
                game.delete()
                return redirect(return_url(request, fallback="games:list_games"))
            recorded = record_facts_for_request(
                request,
                game,
                status=form.cleaned_data["status"],
                mastered=form.cleaned_data["mastered"],
                excluded_from_unfinished=form.cleaned_data["excluded_from_unfinished"],
                excluded_from_dropped=form.cleaned_data["excluded_from_dropped"],
                correlation_id=correlation_id,
            )
            if not recorded:
                #: Re-rendering would invite a second game.
                return redirect(return_url(request, fallback="games:list_games"))
            messages.success(request, f"Game “{game.name}” added.")
            if "submit_and_add_to_library" in request.POST:
                return redirect(
                    action_url(
                        "games:add_to_library",
                        origin=origin_from(request),
                        facts={"game": str(game.id)},
                    )
                )
            return CreatedRedirect(
                return_url(request, fallback="games:list_games"),
                option=game_option(game),
            )

    return render_page(
        request,
        AddForm(
            form,
            request=request,
            fields=Fragment(
                FormFields(form, groups=GAME_FORM_GROUPS),
                #: Its element needs the kind select.
                None
                if form.stated("kind", str) is not None
                else GameAddon("kind", "parent"),
                FieldMirror("name", "sort_name"),
                editions_area(graph),
                references_area(references),
            ),
            additional_row=ControlButton(
                color="gray",
                type="submit",
                name="submit_and_add_to_library",
            )["Submit & Add to library"],
        ),
        title=_add_game_title(form, request.GET.get("addon", "")),
        width="form",
    )


_ADDON_TITLE_LENGTH = Game._meta.get_field("name").max_length


def _add_game_title(form: GameForm, addon: str) -> str:
    """The title, naming the link's add-on."""
    printable = "".join(
        character if character.isprintable() else " " for character in addon
    )
    named = " ".join(printable.split())
    if form.stated("kind", str) == GameKind.MAIN and named:
        return f"Add the main game of {named[:_ADDON_TITLE_LENGTH]}"
    return "Add New Game"


@login_required
@require_POST
def restore_game(request: HttpRequest, game_id: UUID) -> HttpResponse:
    """Undo; the plain manager, since the row is removed."""
    library = cast(User, request.user).library
    game = owned_or_404(Game.objects.restorable_by(library), library, id=game_id)
    return restore_and_return(
        request,
        action=partial(restore_game_for_request, request, game),
        restored=f"{game.name} restored to your library.",
        fallback="games:list_games",
        retry=True,
    )


@login_required
def remove_game(request: HttpRequest, game_id: UUID) -> HttpResponse:
    library = cast(User, request.user).library
    game = owned_or_404(Game.objects.removable_by(library), library, id=game_id)
    return confirm_and_remove(
        request,
        game,
        title="Remove game",
        message=f"Remove {game.name} from your library?",
        details=_removed_with_game(game, library),
        fallback="games:list_games",
        detail_url=game.get_absolute_url(),
        action=partial(remove_game_for_request, request, game),
        removed=f"{game.name} removed from your library.",
        undo="games:restore_game",
    )


def _removed_with_game(game: Game, library: UserLibrary) -> Node:
    departing = game_departures(library, game)
    counts = [
        (departing.sessions, "session"),
        (departing.purchases, "purchase"),
        #: Removal stamps the PlayerGame; runs leave too.
        (departing.runs, "playthrough"),
    ]
    present = [Li()[f"{count} {label}(s)"] for count, label in counts if count]
    if departing.addons:
        present.append(Li()[ADDONS_STAY.format(count=departing.addons)])
    return Ul()[*(present or [Li()["No associated data"]])]


@login_required
def edit_game(request: HttpRequest, game_id: UUID) -> HttpResponse:
    library = cast(User, request.user).library
    game = owned_or_404(Game.objects.for_library(library), library, id=game_id)
    presentation = date_time_presentation_for_request(request)
    form = GameForm(
        request.POST or None,
        instance=game,
        library=library,
        presentation=presentation,
    )
    graph = CatalogGraphForm(
        request.POST or None, game=game, library=library, presentation=presentation
    )
    references = ReferenceSetForm(request.POST or None, target=game, library=library)
    refused_status = 200
    #: Both read; see `add_game` for why the order is not `and`.
    game_reads = form.is_valid()
    references_read = references.is_valid()
    if graph.is_valid() and game_reads and references_read:
        written = submitted_game_or_form_error(form, graph, references)
        if written is not None:
            answer = record_facts_for_request(
                request,
                written,
                status=form.cleaned_data["status"],
                mastered=form.cleaned_data["mastered"],
                excluded_from_unfinished=form.cleaned_data["excluded_from_unfinished"],
                excluded_from_dropped=form.cleaned_data["excluded_from_dropped"],
                correlation_id=new_correlation_id(),
            )
            if answer.refusal is None:
                return redirect(return_url(request, fallback="games:list_games"))
            refused_status = answer.refusal.status_code
            #: The graph is written. Drawing it from storage rather
            #: than from the post is what makes the resubmit below
            #: land on those rows instead of making new ones.
            graph = CatalogGraphForm(
                None, game=written, library=library, presentation=presentation
            )
            references = ReferenceSetForm(None, target=written, library=library)
    #: A failed command lands here too: redirecting would read as
    #: a save. An edit resubmits onto the same row, so re-rendering
    #: invites no duplicate.
    return render_page(
        request,
        AddForm(
            form,
            request=request,
            fields=Fragment(
                FormFields(form, groups=GAME_FORM_GROUPS),
                GameAddon("kind", "parent"),
                editions_area(graph),
                references_area(references),
            ),
        ),
        title="Edit Game",
        width="form",
        #: The same tail renders an invalid form.
        status=refused_status,
    )


# --- view_game content builders -------------------------------------------

#: The glyph beside each stat.
_STAT_GLYPHS = {
    "hours": "clock",
    "sessions": "hash",
    "average": "chart-column",
    "playrange": "calendar-days",
}


def _game_fact(game: Game) -> LinkFacts | None:
    """The game, for forms that take it."""
    #: Session and run forms take owned games.
    return None if game.library_id is None else {"game": str(game.id)}


def _played_row(game: Game, origin: OriginUrl | None, played: int) -> Node:
    """'Played N times' split button; completed runs."""
    from common.components import (
        ControlButton,
        DropdownLinkItem,
        SplitButtonDropdown,
        form_dialog_link,
    )

    count_button = ControlButton(
        variant="outline",
        href=action_url("games:add_playthrough", origin=origin, facts=_game_fact(game)),
    )[
        # One prose phrase = one flex item: the button is inline-flex, and flex
        # layout drops whitespace-only text between items, so the space must
        # live inside a single inline context.
        Span()[Span(data_count="")[str(played)], " times"]
    ]
    items = [
        DropdownLinkItem(
            action_url("games:add_playthrough", origin=origin, facts=_game_fact(game)),
            "Add playthrough\u2026",
        )
    ]
    if game.tracked_status is not None:
        items.append(
            DropdownLinkItem(
                action_url("games:state_times_played", game.pk, origin=origin),
                "Set times played\u2026",
                attributes=form_dialog_link(),
            )
        )
    dropdown = SplitButtonDropdown(
        primary=count_button,
        id=f"played-{game.id}",
        aria_label="Playthrough actions",
        items=items,
    )
    return Div(class_="flex gap-2 items-center")[
        Span(class_="uppercase")["Played"], dropdown
    ]


#: Where a stat's value starts: past its ``size-6`` icon and the ``gap-2``.
_STAT_VALUE_INDENT_CLASS = "ml-8"


def _stat_popover(
    popover_id: str,
    tooltip: str,
    svg_key: str,
    value: Node | str,
    details: Node | None = None,
    *,
    beneath: Node | None = None,
) -> Node:
    """One header stat. ``details`` adds rows beneath the tooltip line — the
    playtime stat puts its alternate formats there rather than nesting a second
    popover inside this one.

    ``beneath`` hangs a second line under the value, outside the popover and
    indented to start where the value does. The popover keeps the one-line
    anatomy the other stats share, so its icon and reveal glyph sit where
    theirs do; inside the popover a second line would move both, because the
    glyph centres against the whole trigger."""
    content: Node | str = (
        tooltip
        if details is None
        else Div(class_="flex flex-col gap-1")[tooltip, details]
    )
    popover = Popover(
        popover_content=content,
        wrapped_classes="flex gap-2 items-center",
        id=popover_id,
        children=[Icon(_STAT_GLYPHS[svg_key], size="size-6", decorative=True), value],
    )
    if beneath is None:
        return popover
    return Div(class_="flex flex-col")[
        popover, Div(class_=_STAT_VALUE_INDENT_CLASS)[beneath]
    ]


def _meta_row(label: str, value: Node | str, extra: Node | str = "") -> Node:
    children: list[Node | str] = [
        Span(class_="uppercase")[label],
        value,
    ]
    if extra:
        children.append(extra)
    return Div(class_="flex gap-2 items-center")[*children]


def _visibility_row(game: Game) -> list[Node]:
    """What the game is left out of."""
    left_out = [
        shown
        for excluded, shown in (
            (game.tracked_excluded_from_unfinished, "unfinished lists"),
            (game.tracked_excluded_from_dropped, "dropped figures"),
        )
        if excluded
    ]
    if not left_out:
        return []
    return [
        _meta_row(
            "Visibility",
            Span(class_=META_VALUE_CLASS)[f"Left out of {', '.join(left_out)}"],
        )
    ]


def _game_action_buttons(game: Game, origin: OriginUrl | None) -> Node:
    # A segmented button group, same component as the table Actions cells. The
    # group owns position-based rounding and hover styling; margin is ours.
    return Div(class_="mb-3")[
        ButtonGroup(
            [
                {
                    "href": action_url(
                        "games:add_session", origin=origin, facts=_game_fact(game)
                    ),
                    "slot": Span(class_="inline-flex items-center gap-1")[
                        Icon("play", size=ICON_BUTTON_SIZE_CLASS), "Log this game"
                    ],
                    "color": "green",
                },
                {
                    "href": action_url("games:edit_game", game.id, origin=origin),
                    "slot": "Edit",
                    "color": "gray",
                },
                {
                    "href": action_url("games:remove_game", game.id, origin=origin),
                    "slot": "Remove",
                    "color": "red",
                },
            ],
        )
    ]


def _game_history(
    entries: Sequence[StatusEntry], presentation: DateTimePresentation
) -> Node:
    items = []
    for entry in entries:
        if entry.recorded_at:
            prefix = f"{presentation.format(entry.recorded_at, 'datetime')}: Changed"
        else:
            prefix = "At some point changed"
        items.append(
            Li(class_="text-body-subtle")[
                f"{prefix} status from",
                GameStatus(status=entry.previous, children=[entry.previous.label]),
                "to",
                GameStatus(status=entry.current, children=[entry.current.label]),
            ]
        )
    return Ul(class_="list-disc list-inside")[*items]


def _game_section(
    title: str,
    count: int,
    table: Node,
    empty_message: str,
    view_all_url: str | None = None,
    add_url: str | None = None,
    organize_url: str | None = None,
    add_control: Node | None = None,
    surface: bool = False,
    view_all_title: str | None = None,
    note: Node | None = None,
) -> Node:
    """``add_control`` replaces Add; ``surface`` adds a panel."""
    buttons: list[Node] = [add_control] if add_control is not None else []
    if add_url:
        #: Offered on an empty section too.
        buttons.append(
            ControlButton(
                href=add_url,
                color="gray",
                title=f"Add {title.lower()} for this game",
            )[
                Icon("plus", size=ICON_BUTTON_SIZE_CLASS),
                "Add",
            ]
        )
    #: View all shows beside a note.
    if view_all_url and (count or note):
        buttons.append(
            ControlButton(
                href=view_all_url,
                color="gray",
                title=view_all_title or f"View all {title.lower()} for this game",
            )[
                Icon("arrowright", size=ICON_BUTTON_SIZE_CLASS),
                "View all",
            ]
        )
    if organize_url and count:
        buttons.append(
            ControlButton(
                href=organize_url,
                color="gray",
                title=f"Organize {title.lower()} by playthrough",
            )[
                Icon("list-tree", size=ICON_BUTTON_SIZE_CLASS),
                "Organize",
            ]
        )
    heading = PageHeading(children=[title], badge=str(count) if count else "")
    if buttons:
        # No margin: the section wrapper's gap owns the distance to the table, so
        # a section with buttons spaces exactly like one without.
        # Three buttons and a badge outrun a phone.
        header = Div(class_="flex flex-wrap items-center justify-between gap-2")[
            heading,
            Div(class_="flex flex-wrap items-center gap-2")[*buttons],
        ]
    else:
        #: A button row's height, so side-by-side headings align.
        header = Div(class_="flex min-h-control items-center")[heading]
    return Div(
        class_=f"mb-6 flex flex-col gap-4 {SECTION_SURFACE_CLASS}"
        if surface
        else "mb-6 flex flex-col gap-4"
    )[
        header,
        table if count else P(class_="text-type-body text-body-subtle")[empty_message],
        P(
            class_=(
                "flex items-center justify-center gap-2 text-type-body text-body-subtle"
            )
        )[Icon("info", [("aria-hidden", "true")]), note]
        if note
        else None,
    ]


def _game_overview_metrics(sessions: PlayerSessionQuerySet) -> dict[str, Any]:
    """Request-free header metrics: total session count, play range, and the
    per-session average of elapsed time over the rows that state an end."""
    session_count = sessions.count()
    days = sessions.aggregate(first=Min("effective_day"), last=Max("effective_day"))

    #: Elapsed time, not the stated duration: a Corrected row's override
    #: and a Duration-only row's stated time are hand-written figures.
    timed = sessions.filter(ended_at__gt=F("started_at")).aggregate(
        total=Sum(F("ended_at") - F("started_at")), rows=Count("id")
    )
    elapsed_total = timed["total"] or timedelta(0)
    session_average_without_manual = round(
        safe_division(elapsed_total.total_seconds() / 3600, int(timed["rows"])), 1
    )
    return {
        "session_count": session_count,
        "playrange_start": days["first"],
        "playrange_end": days["last"],
        "session_average_without_manual": session_average_without_manual,
    }


def _platform_words(release: Release | None) -> str:
    """The Platform a Release names, or Unspecified."""
    if release is None or release.platform is None:
        return UNSPECIFIED_PLATFORM
    return release.platform.name


def _reads_plainly(entries: Sequence[EditionEntry]) -> bool:
    """At most one plain Edition and Release."""
    if len(entries) > 1:
        return False
    if not entries:
        return True
    entry = entries[0]
    return (
        not entry.edition.name
        and entry.edition.kind == EditionKind.FULL
        and len(entry.releases) <= 1
    )


def _edition_name_cell(edition: Edition) -> Node:
    """The name, with a prerelease chip."""
    if edition.kind != EditionKind.PRERELEASE:
        return Fragment(edition.display_name)
    return Span(class_="inline-flex flex-wrap items-center gap-2")[
        edition.display_name,
        Chip(tone="neutral")[EditionKind.PRERELEASE.label],
    ]


def _catalog_controls_visible(game: Game) -> bool:
    """A shared Game is read-only for everyone."""
    return game.library_id is not None


def _release_words(release: Release, presentation: DateTimePresentation) -> str:
    """One Release as a phrase: the Platform, then when it landed."""
    platform = _platform_words(release)
    when = present_temporal_value(release.release_date, presentation)
    return platform if when == UNKNOWN_TEXT else f"{platform} ({when})"


def _platforms_cell(entry: EditionEntry, presentation: DateTimePresentation) -> str:
    """Every Release of one Edition, in one cell.

    A comma list rather than a cell each: the table hides a column
    by position, thus a row states exactly one cell per column.
    """
    if not entry.releases:
        return "No releases yet."
    return ", ".join(
        _release_words(release, presentation) for release in entry.releases
    )


def _plain_release_rows(
    entries: Sequence[EditionEntry],
    presentation: DateTimePresentation,
) -> list[Node]:
    """The header states an ordinary Game's Release."""
    if not _reads_plainly(entries):
        return []
    releases = entries[0].releases if entries else ()
    release = releases[0] if releases else None
    rows: list[Node] = [
        _meta_row(
            "Platform",
            Span(class_=META_VALUE_CLASS)[_platform_words(release)],
        ),
        _meta_row(
            "Released",
            TemporalText(
                None if release is None else release.release_date,
                presentation,
                class_=META_VALUE_CLASS,
            ),
        ),
    ]
    #: Nothing to press here: Edit Game owns the whole graph.
    return rows


def _references_row(references: Sequence[ExternalReference]) -> list[Node]:
    """No row when nothing is named outside."""
    if not references:
        return []
    return [_meta_row("References", ExternalReferenceLinks(references))]


def _references_cell(entry: EditionEntry, references: ReferenceMap) -> Node:
    """One Edition's references, then its Releases'."""
    held = held_by(references, entry.edition.pk)
    for release in entry.releases:
        held.extend(held_by(references, release.pk))
    return ExternalReferenceLinks(held)


def _releases_section(
    entries: Sequence[EditionEntry],
    presentation: DateTimePresentation,
    origin: OriginUrl | None,
    *,
    game: Game,
    references: ReferenceMap,
) -> Node:
    """What the header's two rows cannot say.

    One read-only row per Edition. Every edit goes to the Game
    form, which states the whole graph in one transaction, so
    nothing here writes.

    A placeholder, and it says so on the page. `Edition` and
    `Release` are the words the schema needs for IGDB, not words
    a reader wants: nothing a person makes names either one, and
    every one of 858 real Games holds exactly one of each. The
    section worth having states the playtime of each edition,
    which #690 makes readable by letting a Session name a
    Release. This shape is replaced then.
    """
    if _reads_plainly(entries):
        return Fragment()
    controls = _catalog_controls_visible(game)
    columns = [
        Column("Name"),
        Column("Platforms", wrap=True),
        Column("References", priority=2),
    ]
    if controls:
        columns.append(Column("Actions", align="right", priority=3))
    #: One link, drawn once per row: the form owns every Edition.
    edit = Div(class_="flex justify-end")[
        ControlButton(
            href=action_url("games:edit_game", game.pk, origin=origin), color="gray"
        )["Edit"]
    ]
    rows = [
        make_row(
            _edition_name_cell(entry.edition),
            _platforms_cell(entry, presentation),
            _references_cell(entry, references),
            *((edit,) if controls else ()),
        )
        for entry in entries
    ]
    return Div(class_="mb-6 flex flex-col gap-4")[
        PageHeading(children=["Editions"], badge=str(len(entries))),
        P(
            class_="text-type-body text-warning bg-warning-soft "
            "border border-warning-subtle rounded px-3 py-2"
        )[EDITIONS_UNDER_CONSTRUCTION],
        StyledTable(
            columns=columns,
            rows=rows,
            data_table=True,
            caption=f"Editions of {game.name}",
            #: Two Games may share a name; their ids may not.
            caption_key=str(game.pk),
        ),
    ]


def _game_header(
    game: Game,
    request: HttpRequest,
    metrics: dict[str, Any],
    playtime: PlaytimeBreakdown,
    presentation: DateTimePresentation,
    durations: DurationPresentation,
    origin: OriginUrl | None,
    entries: Sequence[EditionEntry],
    references: Sequence[ExternalReference],
    played: int,
    library: UserLibrary,
) -> Node:
    playrange_start = metrics["playrange_start"]
    playrange_end = metrics["playrange_end"]
    if playrange_start and playrange_end:
        start = presentation.format(playrange_start, "month_year")
        end = presentation.format(playrange_end, "month_year")
        playrange = start if start == end else f"{start} — {end}"
    else:
        playrange = "N/A"
    title_span = Span(class_="text-balance max-w-120")[
        Span(class_="text-type-title font-serif text-heading")[game.name],
    ]
    stats_row = Div(class_="flex gap-4 text-type-body mb-3")[
        _stat_popover(
            "popover-hours",
            "Total hours played",
            "hours",
            DurationText(playtime.total, durations),
            DurationAlternates(playtime.total, durations),
            beneath=(
                PlaytimeHalves(playtime, durations) if playtime.historical else None
            ),
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
            playrange,
        ),
    ]
    metadata = Div(
        class_="flex flex-col mb-6 text-body gap-y-4 text-type-body",
    )[
        *_parent_row(game, library),
        _meta_row(
            "Original release",
            TemporalText(
                game.original_release_date, presentation, class_=META_VALUE_CLASS
            ),
        ),
        *_references_row(references),
        _meta_row(
            "Status",
            Span()[
                GameStatusSelector(
                    game,
                    PlayerGameStatus.choices,
                    get_token(request),
                    current=game.tracked_status,
                )
            ],
            "👑" if game.tracked_mastered else "",
        ),
        *_visibility_row(game),
        _played_row(game, origin, played),
        *_plain_release_rows(entries, presentation),
    ]
    return Div(id_="game-info", class_="mb-10")[
        Div(class_="flex gap-5 mb-3")[title_span],
        stats_row,
        metadata,
        _game_action_buttons(game, origin),
    ]


def _parent_row(game: Game, library: UserLibrary) -> list[Node]:
    """The parent, linked where the page exists."""
    if game.parent_id is None:
        return []
    parent = Game.objects.get(pk=game.parent_id)
    name: Node
    if foreign_to(parent, library):
        logger.error("Game %s names foreign parent %s.", game.pk, parent.pk)
        name = Span(class_=META_VALUE_CLASS)[FOREIGN_PARENT_LABEL]
    elif parent.removed_at is not None:
        name = Span(class_=META_VALUE_CLASS)[f"{parent.name} (removed)"]
    elif Game.objects.tracked_by(library).filter(pk=parent.pk).exists():
        name = Link(href=parent.get_absolute_url(), class_=META_VALUE_CLASS)[
            parent.name
        ]
    else:
        name = Span(class_=META_VALUE_CLASS)[parent.name]
    return [
        _meta_row("Add-on of", name, Chip(tone="neutral")[GameKind(game.kind).label])
    ]


def _addons_section(game: Game, library: UserLibrary, origin: OriginUrl | None) -> Node:
    """Tracked add-ons; nothing when none."""
    addons = list(tracked_addons(library, game))
    if not addons:
        return Fragment()
    by_kind: dict[GameKind, list[Game]] = {}
    for addon in addons:
        by_kind.setdefault(GameKind(addon.kind), []).append(addon)
    groups = [
        SummaryGroup(
            label=kind.label,
            rows=[
                SummaryRow(
                    label="",
                    subtitle=Fragment(
                        Link(href=addon.get_absolute_url())[addon.name],
                        Span()[f"· {PlayerGameStatus(addon.tracked_status).label}"],
                    ),
                    control=game_row_menu(addon, origin, size="compact"),
                    dense=True,
                )
                for addon in by_kind[kind]
            ],
        )
        for kind in GameKind
        if kind in by_kind
    ]
    return Div(id_="addons", class_=_GRID_CELL_CLASS)[
        _game_section(
            "Add-ons",
            len(addons),
            SummaryList(*groups, labelled=True),
            "",
            surface=True,
        )
    ]


def _sessions_section(
    game: Game,
    sessions: PlayerSessionQuerySet,
    presentation: DateTimePresentation,
    durations: DurationPresentation,
) -> Node:
    sessions = sessions.select_related("device").order_by("-sort_instant", "-id")
    session_count = sessions.count()
    rows = [
        make_row(
            session_time_range(session, presentation),
            Duration(
                session.effective_duration,
                durations,
                id_scope=f"game-session-{session.pk}",
                manual=session.timing_mode != PlayerSessionTimingMode.TIMED,
            ),
            session.device.name if session.device else "No device",
        )
        for session in sessions[:5]
    ]
    table = StyledTable(
        columns=[
            Column("Date"),
            Column("Duration", priority=2),
            Column("Device"),
        ],
        rows=rows,
        data_table=True,
        caption="Recent sessions of this game",
    )
    return _game_section(
        "Sessions",
        session_count,
        table,
        "No sessions yet.",
        view_all_url=filter_url(PlayerSessionFilter.where(game=[game.id])),
        organize_url=filter_url(
            PlayerSessionFilter.where(game=[game.id]), sort="playthrough"
        ),
    )


def _historical_playtime_section(
    game: Game,
    library: UserLibrary,
    presentation: DateTimePresentation,
    durations: DurationPresentation,
    origin: OriginUrl | None,
    request: HttpRequest,
) -> Node:
    records = list(
        listed_records(library).filter(player_game__game=game).order_by(*RECORD_ORDER)
    )
    data = historical_playtime_tabledata(
        records,
        run_labels_for(library, records),
        presentation,
        durations,
        hidden=("name", "release", "created"),
        origin=origin,
        caption="Historical playtime of this game",
    )
    table = StyledTable(
        columns=data["columns"],
        rows=data["rows"],
        data_table=True,
        caption="Historical playtime of this game",
        #: The request scopes the kept selection to this library.
        request=request,
        selection=SelectionDeclaration(
            #: The act's scope is the library's, not this game's: an
            #: "all" statement here would name every record the library
            #: holds. This section states no paginator, so the line
            #: renders no "select all matching" and the statement it
            #: posts is always the keys a person marked.
            filter="",
            csrf_token=get_token(request),
            actions=tray_actions(REMOVE_RECORD.name, origin=origin),
        ),
    )
    section = _game_section(
        "Historical playtime",
        len(records),
        table,
        "No historical playtime.",
        view_all_url=filter_url(HistoricalPlaytimeFilter.where(game=[game.id])),
        add_url=action_url("games:add_historical_playtime", game.pk, origin=origin),
    )
    return Div(id_="historical-playtime-container")[section]


def _playthroughs_section(
    game: Game,
    runs: Sequence[Playthrough],
    presentation: DateTimePresentation,
    clock: ActivityClock,
    origin: OriginUrl | None,
    csrf_token: str,
    request: HttpRequest,
) -> Node:
    data = playthrough_tabledata(
        runs,
        presentation,
        #: Every row names this game, and Created earns its width as seldom
        #: here as it does on the list, which starts it off.
        hidden=("game", "created"),
        clock=clock,
        origin=origin,
        csrf_token=csrf_token,
    )
    # This embedded mini-table isn't a sortable list view (no ?sort= handling on
    # the detail page), and its builder states no sort keys.
    table = StyledTable(
        columns=data["columns"],
        rows=data["rows"],
        data_table=True,
        caption="Playthroughs of this game",
        #: The request scopes the kept selection to this library.
        request=request,
        selection=SelectionDeclaration(
            #: The act's scope is the library's, not this game's: an
            #: "all" statement here would name every run the library
            #: holds. This section states no paginator, so the line
            #: renders no "select all matching" and the statement it
            #: posts is always the keys a person marked.
            filter="",
            csrf_token=csrf_token,
            actions=tray_actions(
                START_RUNS.name,
                COMPLETE_RUNS.name,
                REMOVE_RUN.name,
                origin=origin,
            ),
        ),
    )
    section = _game_section(
        "Playthroughs",
        len(runs),
        table,
        #: Reachable: conversion skipped a tracked game
        #: whose catalog row was removed.
        "No playthroughs yet.",
        view_all_url=filter_url(PlaythroughFilter.where(game=[game.id])),
    )
    return Div(id_="playthroughs-container")[section]


def _plural(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"


def _previous_note(game: Game, copies: CopyRows) -> Node | None:
    """Counts what the cards leave out, linked."""
    parts: list[Node | str] = []
    if copies.ended:
        parts.append(
            Link(href=filter_url(previous_copies_filter(game)))[
                _plural(copies.ended, "more copy", "more copies")
            ]
        )
        if copies.ended_purchases:
            parts += [
                " (with ",
                Link(href=filter_url(previous_copy_purchases_filter(game)))[
                    _plural(copies.ended_purchases, "purchase", "purchases")
                ],
                ")",
            ]
    if copies.refunded_purchases:
        if parts:
            parts.append(" and ")
        parts.append(
            Link(href=filter_url(refunded_held_purchases_filter(game)))[
                _plural(copies.refunded_purchases, "more purchase", "more purchases")
            ]
        )
    if not parts:
        return None
    leading = copies.ended or copies.refunded_purchases
    #: One inline run: the note's P is flex.
    return Span()[
        "There is " if leading == 1 else "There are ",
        *parts,
        " previously in your library.",
    ]


def _library_section(
    game: Game,
    library: UserLibrary,
    presentation: DateTimePresentation,
    origin: OriginUrl,
    csrf_token: str,
) -> Node:
    copies = copy_rows(game, library, presentation, origin, csrf_token)
    add = library_add_control(game, library, origin, csrf_token)
    empty = EMPTY_LIBRARY if add is not None else SHARED_GAME_RELEASE
    if copies.ended and not copies.held:
        empty = EMPTY_LIBRARY_NOW
    return Div(id_="library", class_=_GRID_CELL_CLASS)[
        _game_section(
            "Library",
            copies.held,
            SummaryList(*copies.rows, labelled=True),
            empty,
            add_control=add,
            surface=True,
            view_all_url=filter_url(LibraryEntryFilter.where(game=[game.id])),
            view_all_title="View all copies of this game",
            note=_previous_note(game, copies),
        )
    ]


def _history_section(
    game: Game, library: UserLibrary, presentation: DateTimePresentation
) -> Node:
    #: A stream belongs to one library.
    entries = status_history(library, game)
    count = len(entries)
    return _RefreshingSection(
        class_="mb-6 flex flex-col gap-4",
        id="history-container",
        #: The status selector's event.
        event="status-changed",
    )[
        PageHeading(children=["History"], badge=str(count) if count else ""),
        _game_history(entries, presentation),
    ]


@login_required
def view_game(request: HttpRequest, game_id: UUID, slug: str) -> HttpResponse:
    library = cast(User, request.user).library
    game = owned_or_404(Game.objects.tracked_by(library), library, id=game_id)
    if slug != game.url_slug:
        return _canonical_game_redirect(request, game)
    presentation = date_time_presentation_for_request(request)
    durations = duration_presentation_for_request(request)
    origin = request.get_full_path()
    #: Scoped, not `game.sessions` and friends: tracked_by() admits a
    #: shared catalog game, and a shared game's reverse accessors reach
    #: every library that ever wrote against it.
    sessions = shown_sessions(library).filter(**{GAME: game})
    tracked = tracked_game(library, game)
    #: A run may name another library's PlayerGame.
    runs = list(
        numbered_for(
            library, [tracked.pk] if tracked else [], with_condition=True
        ).select_related("player_game__game")
    )
    #: Counted here, off rows already read.
    played = sum(1 for run in runs if run.completion_recorded_at is not None)
    hierarchy = game_hierarchy(game, library)
    #: One batch, one query per kind.
    referenced: list[CatalogTarget] = [game]
    for entry in hierarchy:
        referenced.append(entry.edition)
        referenced.extend(entry.releases)
    references = references_for(referenced)
    content = Div()[
        _game_header(
            game,
            request,
            _game_overview_metrics(sessions),
            game_playtime(library, game),
            presentation,
            durations,
            origin,
            hierarchy,
            held_by(references, game.pk),
            played,
            library,
        ),
        _releases_section(
            hierarchy, presentation, origin, game=game, references=references
        ),
        #: Half width each on wide screens.
        Div(class_="grid grid-cols-1 items-start lg:grid-cols-2 lg:gap-x-6")[
            _addons_section(game, library, origin),
            _library_section(game, library, presentation, origin, get_token(request)),
        ],
        _sessions_section(game, sessions, presentation, durations),
        _historical_playtime_section(
            game, library, presentation, durations, origin, request
        ),
        _playthroughs_section(
            game,
            runs,
            presentation,
            activity_clock(library),
            origin,
            get_token(request),
            request,
        ),
        _history_section(game, library, presentation),
    ]
    return render_page(
        request,
        content,
        title=f"Game Overview - {game.name}",
        width="full",
    )


def _canonical_game_redirect(request: HttpRequest, game: Game) -> HttpResponse:
    target = game.get_absolute_url()
    query = request.GET.urlencode()
    if query:
        target = f"{target}?{query}"
    return redirect(target, permanent=True)


def retired_game_view(request: HttpRequest, game_id: UUID) -> NoReturn:
    raise Http404
