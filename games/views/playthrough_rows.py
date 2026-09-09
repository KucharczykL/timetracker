"""One table row per run."""

from collections.abc import Mapping, Sequence
from typing import Any

from common.components import (
    ICON_BUTTON_SIZE_CLASS,
    ButtonGroup,
    ButtonGroupMember,
    Cell,
    Column,
    Icon,
    TableData,
    TruncatedText,
    make_row,
)
from common.date_time_presentation import DateTimePresentation
from common.returns import OriginUrl, action_url
from common.sorting import SortKey, SortTerm
from common.temporal_presentation import TemporalText
from games.models import Playthrough
from games.reads.playthrough_endpoints import (
    StatedEndpoint,
    days_to_finish,
    stated_completion,
    stated_start,
)
from games.reads.playthrough_numbering import display_name

#: The list page's sort keys, by label.
_SORT_KEYS: Mapping[str, SortKey] = {
    "Game": "name",
    "Started": "started",
    "Completed": "completed",
    "Days to finish": "days",
    "Created": "created",
}


def playthrough_tabledata(
    runs: Sequence[Playthrough],
    presentation: DateTimePresentation,
    exclude_columns: Sequence[str] = (),
    *,
    origin: OriginUrl | None,
    sort_terms: Sequence[SortTerm] = (),
    sortable: bool = False,
    csrf_token: str = "",
) -> TableData:
    """Rows for the runs; caller states sorting."""

    def column(label: str, **options: Any) -> Column:
        return Column(label, _SORT_KEYS.get(label) if sortable else None, **options)

    column_list = [
        column("Playthrough", shrinkable=True),
        column("Game", shrinkable=True),
        column("Started", priority=3),
        column("Completed", priority=2),
        column("Days to finish", priority=2),
        # One long note on one line widens everything.
        column("Note", wrap=True),
        column("Created"),
        column("Actions", align="right", priority=4),
    ]
    kept_columns = [
        column for column in column_list if column.label not in exclude_columns
    ]
    dropped_indexes = [
        index
        for index, column in enumerate(column_list)
        if column.label in exclude_columns
    ]

    row_list: list[list[Cell]] = [
        [
            #: Pinned first column: clip a stated name.
            TruncatedText(display_name(run)),
            TruncatedText(
                run.player_game.game.name,
                link=run.player_game.game.get_absolute_url(),
            ),
            _endpoint_cell(stated_start(run), presentation),
            _endpoint_cell(stated_completion(run), presentation),
            _days_cell(run),
            run.note,
            presentation.format(run.created_at, "date"),
            _actions(run, origin, csrf_token),
        ]
        for run in runs
    ]
    kept_rows = [
        [cell for index, cell in enumerate(row) if index not in dropped_indexes]
        for row in row_list
    ]
    return {
        "caption": "Playthroughs",
        "columns": kept_columns,
        "sort_terms": sort_terms,
        "rows": [make_row(*cells) for cells in kept_rows],
    }


def _endpoint_cell(
    stated: StatedEndpoint | None, presentation: DateTimePresentation
) -> Cell:
    """No act reads a dash, unknown day `Unknown`."""
    if stated is None:
        return "-"
    return TemporalText(stated.when, presentation)


def _days_cell(run: Playthrough) -> Cell:
    days = days_to_finish(run)
    return "-" if days is None else str(days)


def _actions(run: Playthrough, origin: OriginUrl | None, csrf_token: str) -> Cell:
    """The act this run allows, then edit and remove.

    One press states today. A day that is not today
    belongs in the edit form, which holds every precision
    the grammar knows.

    Remove renders on the last run too: the command owns
    that refusal, and a second gate can disagree with it.
    """
    return ButtonGroup(
        [
            _act_member(run, origin, csrf_token),
            {
                "href": action_url("games:edit_playthrough", run.pk, origin=origin),
                "slot": Icon("edit", size=ICON_BUTTON_SIZE_CLASS),
                "color": "gray",
            },
            {
                "href": action_url("games:remove_playthrough", run.pk, origin=origin),
                "slot": Icon("delete", size=ICON_BUTTON_SIZE_CLASS),
                "color": "red",
            },
        ]
    )


def _act_member(
    run: Playthrough, origin: OriginUrl | None, csrf_token: str
) -> ButtonGroupMember:
    """Start, complete, or nothing left to state.

    An empty member renders nothing: ButtonGroup skips a
    dict with no slot.
    """
    if stated_start(run) is None:
        return {
            "slot": Icon("play", size=ICON_BUTTON_SIZE_CLASS),
            "title": "Started today",
            "color": "green",
            "method": "post",
            "action": action_url("games:start_playthrough", run.pk, origin=origin),
            "csrf_token": csrf_token,
        }
    if stated_completion(run) is None:
        return {
            "slot": Icon("finish", size=ICON_BUTTON_SIZE_CLASS),
            "title": "Completed today",
            "color": "green",
            "method": "post",
            "action": action_url("games:complete_playthrough", run.pk, origin=origin),
            "csrf_token": csrf_token,
        }
    return {}
