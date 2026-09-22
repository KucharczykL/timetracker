"""One table row per run."""

from collections.abc import Mapping, Sequence
from typing import Any

from common.components import (
    Cell,
    Column,
    ColumnKey,
    DropdownLinkItem,
    DropdownPostItem,
    Fragment,
    Node,
    Pill,
    RowActionMenu,
    Span,
    TableData,
    TruncatedText,
    make_row,
    row_summary,
)
from common.date_time_presentation import DateTimePresentation
from common.returns import OriginUrl, action_url
from common.sorting import SortKey, SortTerm
from common.temporal_presentation import TemporalText, present_temporal_value
from games.bulk_actions import BulkAction
from games.bulk_playthrough_acts import COMPLETE_RUNS, START_RUNS
from games.bulk_tray import one_row_statement
from games.models import Playthrough
from games.reads.playthrough_activity import (
    ActivityClock,
    RunActivity,
    recency_phrase,
)
from games.reads.playthrough_endpoints import (
    StatedEndpoint,
    days_to_finish,
    stated_completion,
    stated_start,
)
from games.reads.playthrough_numbering import display_name
from timetracker.temporal import TemporalEndpoint, TemporalValue

#: One request's CSRF token, as the act forms post it.
type CsrfToken = str

#: The list page's sort keys, by label.
_SORT_KEYS: Mapping[str, SortKey] = {
    "Playthrough": "playthrough",
    "Game": "name",
    "Started": "started",
    "Completed": "completed",
    "Days to finish": "days",
    "Created": "created",
}


def playthrough_columns(*, sortable: bool) -> list[Column]:
    """The run table's columns, in declaration order."""

    def column(label: str, key: ColumnKey, **options: Any) -> Column:
        return Column(
            label, _SORT_KEYS.get(label) if sortable else None, key=key, **options
        )

    return [
        column("Playthrough", "playthrough", shrinkable=True, hideable=False),
        column("Game", "game", shrinkable=True),
        column("Started", "started", priority=3),
        column("Completed", "completed", priority=2),
        #: Below Note: counted word yields to note.
        column("Activity", "activity", priority=1),
        column("Days to finish", "days", priority=2),
        # One long note on one line widens everything.
        column("Note", "note", wrap=True, priority=2),
        column("Created", "created"),
    ]


def playthrough_tabledata(
    runs: Sequence[Playthrough],
    presentation: DateTimePresentation,
    exclude_columns: Sequence[str] = (),
    *,
    clock: ActivityClock,
    origin: OriginUrl | None,
    csrf_token: CsrfToken,
    sort_terms: Sequence[SortTerm] = (),
    sortable: bool = False,
) -> TableData:
    """Rows for the runs; caller states sorting.

    The token has no default: an act button posts, and a
    form with no token renders a button that only 403s.

    The clock has none either, and is the one that read
    these runs, so the condition and the recency beside
    it cannot come from two calendars.
    """

    column_list = playthrough_columns(sortable=sortable)
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
            _activity_cell(run, clock),
            _days_cell(run),
            run.note,
            presentation.format(run.created_at, "date"),
        ]
        for run in runs
    ]
    kept_rows = [
        [cell for index, cell in enumerate(row) if index not in dropped_indexes]
        for row in row_list
    ]
    with_game = "Game" not in exclude_columns
    return {
        "caption": "Playthroughs",
        "columns": kept_columns,
        "sort_terms": sort_terms,
        "rows": [
            make_row(
                *cells,
                key=str(run.pk),
                menu=_row_menu(run, origin, csrf_token),
                summary=_summary(run, presentation, clock, with_game=with_game),
            )
            for run, cells in zip(runs, kept_rows, strict=True)
        ],
    }


def _summary(
    run: Playthrough,
    presentation: DateTimePresentation,
    clock: ActivityClock,
    *,
    with_game: bool,
) -> str:
    """The second line, below md, where the columns went.

    The game is named only where its column is declared:
    the list drops it with the rest, and on Game detail
    every row names the same game already.
    """
    return row_summary(
        run.player_game.game.name if with_game else None,
        *_endpoint_parts(run, presentation),
        _activity_part(run, clock),
    )


def _endpoint_parts(
    run: Playthrough, presentation: DateTimePresentation
) -> list[str | None]:
    """One span, or one labelled part per endpoint.

    Two values joined as a range read as one range, which
    is wrong where either is itself a range or unknown.
    """
    start, completion = _stated_values(run)
    span = _span(start, completion, presentation)
    if span is not None:
        return [span]
    return [
        _labelled_endpoint("Started", start, presentation),
        _labelled_endpoint("Completed", completion, presentation),
    ]


def _stated_values(
    run: Playthrough,
) -> tuple[TemporalValue | None, TemporalValue | None]:
    """Each endpoint's value, or nothing.

    An act stated on a day nobody knows states no value:
    the summary drops such a part rather than spending
    the line on the word `Unknown`.
    """
    return tuple(  # type: ignore[return-value]
        None if stated is None else stated.when
        for stated in (stated_start(run), stated_completion(run))
    )


def _span(
    start: TemporalValue | None,
    completion: TemporalValue | None,
    presentation: DateTimePresentation,
) -> str | None:
    """Both endpoints as one range, in the grammar's words.

    The open endpoint is what picks `since` and `until`,
    so an endpoint the run states nothing about is open
    rather than unknown, which would read `Unknown`.
    """
    if start is None and completion is None:
        return None
    if any(
        value.is_range or value.is_unknown for value in (start, completion) if value
    ):
        return None
    return present_temporal_value(
        TemporalValue.range(
            start=_endpoint(start),
            end=_endpoint(completion),
        ),
        presentation,
    )


def _endpoint(value: TemporalValue | None) -> TemporalEndpoint:
    return TemporalEndpoint.open() if value is None else TemporalEndpoint.known(value)


def _labelled_endpoint(
    label: str, value: TemporalValue | None, presentation: DateTimePresentation
) -> str | None:
    if value is None or value.is_unknown:
        return None
    return f"{label} {present_temporal_value(value, presentation)}"


def _activity_part(run: Playthrough, clock: ActivityClock) -> str | None:
    """The clock's word and how long ago, as one part.

    A run that states a completion is counted no
    condition, and states no part.
    """
    if not hasattr(run, "activity"):
        raise ValueError(
            f"playthrough {run.pk} carries no condition alias; "
            "read the runs through runs_with_condition()"
        )
    if run.activity is None:
        return None
    word = RunActivity(run.activity).label
    day = getattr(run, "activity_day", None)
    return word if day is None else f"{word} {recency_phrase(day, clock.today)}"


def _endpoint_cell(
    stated: StatedEndpoint | None, presentation: DateTimePresentation
) -> Cell:
    """No act reads a dash, unknown day `Unknown`."""
    if stated is None:
        return "-"
    return TemporalText(stated.when, presentation)


def _activity_cell(run: Playthrough, clock: ActivityClock) -> Cell:
    """The clock's word, and how long ago.

    An absent alias is a caller who read the runs off a
    queryset no clock reached, and a dash there prints
    every unfinished run as finished.

    Word and phrase read one clock: the row's day is
    counted on the library's calendar, so today is too.
    """
    if not hasattr(run, "activity"):
        raise ValueError(
            f"playthrough {run.pk} carries no condition alias; "
            "read the runs through runs_with_condition()"
        )
    if run.activity is None:
        return "-"
    badge = Pill(label=RunActivity(run.activity).label)
    day = getattr(run, "activity_day", None)
    if day is None:
        return badge
    return Fragment(
        badge,
        Span(class_="ml-2 text-type-body")[recency_phrase(day, clock.today)],
    )


def _days_cell(run: Playthrough) -> Cell:
    days = days_to_finish(run)
    return "-" if days is None else str(days)


def _row_menu(
    run: Playthrough, origin: OriginUrl | None, csrf_token: CsrfToken
) -> Node:
    """The act this run allows, then edit and remove.

    One press states today; another day belongs in the edit form. Remove
    renders on the last run too: the command owns that refusal.
    """
    return RowActionMenu(
        [
            *_act_items(run, origin, csrf_token),
            DropdownLinkItem(
                action_url("games:edit_playthrough", run.pk, origin=origin),
                "Edit",
                icon="edit",
            ),
            DropdownLinkItem(
                action_url("games:remove_playthrough", run.pk, origin=origin),
                "Remove",
                icon="delete",
                danger=True,
            ),
        ],
        label=f"{display_name(run)}, {run.player_game.game.name} actions",
        id=f"run-menu-{run.pk}",
    )


def _act_items(
    run: Playthrough, origin: OriginUrl | None, csrf_token: CsrfToken
) -> list[Node]:
    """The one act this run can still accept, if any.

    A run stating a completion is offered no start, even where it states
    none. The gate is narrower than the command, which takes a start at
    today on a run completed today, on a day nobody wrote down, or on a
    day a qualifier widens: a finished run is not one a person is
    starting now. Zero or one, so the caller spreads it.
    """
    if stated_completion(run) is not None:
        return []
    if stated_start(run) is None:
        return [_act(run, START_RUNS, "play", origin, csrf_token)]
    return [_act(run, COMPLETE_RUNS, "finish", origin, csrf_token)]


def _act(
    run: Playthrough,
    action: BulkAction[Playthrough],
    icon: str,
    origin: OriginUrl | None,
    csrf_token: CsrfToken,
) -> Node:
    """One row, handed to a tray act.

    The act's own label, so it reads the same in both places; its
    confirmation states the status the act also records.
    """
    return DropdownPostItem(
        action_url("games:run_bulk_action", action.name, origin=origin),
        action.label,
        csrf_token=csrf_token,
        hidden_fields=one_row_statement(run.pk),
        icon=icon,
    )
