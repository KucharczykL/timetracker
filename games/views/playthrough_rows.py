"""One table row per run."""

from collections.abc import Sequence

from common.components import (
    ICON_BUTTON_SIZE_CLASS,
    ButtonGroup,
    Cell,
    Column,
    Icon,
    TableData,
    TruncatedText,
    make_row,
)
from common.date_time_presentation import DateTimePresentation
from common.returns import OriginUrl, action_url
from common.temporal_presentation import TemporalText
from games.models import Playthrough
from games.reads.playthrough_endpoints import (
    StatedEndpoint,
    days_to_finish,
    stated_completion,
    stated_start,
)
from games.reads.playthrough_numbering import display_name


def playthrough_tabledata(
    runs: Sequence[Playthrough],
    presentation: DateTimePresentation,
    exclude_columns: Sequence[str] = (),
    *,
    origin: OriginUrl | None,
) -> TableData:
    """The runs, as rows. No sort keys."""
    column_list = [
        Column("Playthrough", shrinkable=True),
        Column("Game", shrinkable=True),
        Column("Started", priority=3),
        Column("Completed", priority=2),
        Column("Days to finish", priority=2),
        # One long note on one line widens everything.
        Column("Note", wrap=True),
        Column("Created"),
        Column("Actions", align="right", priority=4),
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
            display_name(run),
            TruncatedText(
                run.player_game.game.name,
                link=run.player_game.game.get_absolute_url(),
            ),
            _endpoint_cell(stated_start(run), presentation),
            _endpoint_cell(stated_completion(run), presentation),
            _days_cell(run),
            run.note,
            presentation.format(run.created_at, "date"),
            _actions(run, origin),
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
        "sort_terms": (),
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


def _actions(run: Playthrough, origin: OriginUrl | None) -> Cell:
    """Edit and remove, naming the run.

    Remove renders on the last run too: the command owns
    that refusal, and a second gate can disagree with it.
    """
    return ButtonGroup(
        [
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
