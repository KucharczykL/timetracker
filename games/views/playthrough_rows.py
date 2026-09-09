"""One table row per run."""

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from common.components import (
    ICON_BUTTON_SIZE_CLASS,
    ButtonGroup,
    ButtonGroupMember,
    Cell,
    Column,
    Fragment,
    Icon,
    Pill,
    Span,
    TableData,
    TruncatedText,
    make_row,
)
from common.date_time_presentation import DateTimePresentation
from common.returns import OriginUrl, action_url
from common.sorting import SortKey, SortTerm
from common.temporal_presentation import TemporalText
from games.models import Playthrough
from games.reads.playthrough_activity import RunActivity, recency_phrase
from games.reads.playthrough_endpoints import (
    StatedEndpoint,
    days_to_finish,
    stated_completion,
    stated_start,
)
from games.reads.playthrough_numbering import display_name

#: One request's CSRF token, as the act forms post it.
type CsrfToken = str

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
    csrf_token: CsrfToken,
    sort_terms: Sequence[SortTerm] = (),
    sortable: bool = False,
) -> TableData:
    """Rows for the runs; caller states sorting.

    The token has no default: an act button posts, and a
    form with no token renders a button that only 403s.
    """

    def column(label: str, **options: Any) -> Column:
        return Column(label, _SORT_KEYS.get(label) if sortable else None, **options)

    column_list = [
        column("Playthrough", shrinkable=True),
        column("Game", shrinkable=True),
        column("Started", priority=3),
        column("Completed", priority=2),
        column("Activity", priority=3),
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
            _activity_cell(run, presentation),
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


def _activity_cell(run: Playthrough, presentation: DateTimePresentation) -> Cell:
    """The clock's word, and how long ago that was.

    A completed run reads a dash: it is not unfinished, so
    no clock speaks about it. A row from a read that states
    no alias reads one too, rather than raising.
    """
    activity = getattr(run, "activity", None)
    if activity is None:
        return "-"
    badge = Pill(label=RunActivity(activity).label)
    day = getattr(run, "activity_day", None)
    if day is None:
        return badge
    today = datetime.now(presentation.timezone).date()
    return Fragment(
        badge,
        Span(class_="ml-2 text-type-body")[f"last played {recency_phrase(day, today)}"],
    )


def _days_cell(run: Playthrough) -> Cell:
    days = days_to_finish(run)
    return "-" if days is None else str(days)


def _actions(run: Playthrough, origin: OriginUrl | None, csrf_token: CsrfToken) -> Cell:
    """The act this run allows, then edit and remove.

    One press states today; another day belongs
    in the edit form. Remove renders on the last
    run too: the command owns that refusal, and
    a second gate can disagree with it.
    """
    return ButtonGroup(
        [
            *_act_members(run, origin, csrf_token),
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


def _act_members(
    run: Playthrough, origin: OriginUrl | None, csrf_token: CsrfToken
) -> list[ButtonGroupMember]:
    """The one act this run can still accept, if any.

    A run that states a completion is offered no start,
    even where it states none: starting today would end
    the run before it began, and the command refuses
    that. A button whose whole class of row is refused
    is a promise the row cannot keep, which is not the
    race the other gates leave to the command.

    Zero or one, so the caller spreads it.
    """
    if stated_completion(run) is not None:
        return []
    if stated_start(run) is None:
        return [_act(run, "start", origin, csrf_token)]
    return [_act(run, "complete", origin, csrf_token)]


#: How each act's button reads, by route.
#:
#: Only the completion names its status. It states one every
#: time, so the title can promise it; a start states Played
#: only where nothing stronger is stated already, and a title
#: naming a status the press may skip reads as a lie.
_ACT_BUTTONS: Mapping[str, tuple[str, str]] = {
    "start": ("play", "Started today"),
    "complete": ("finish", "Completed today, also marks the game Completed"),
}


def _act(
    run: Playthrough, act: str, origin: OriginUrl | None, csrf_token: CsrfToken
) -> ButtonGroupMember:
    """One press, posting to that act's route."""
    icon, title = _ACT_BUTTONS[act]
    return {
        "slot": Icon(icon, size=ICON_BUTTON_SIZE_CLASS),
        "title": title,
        "color": "green",
        "method": "post",
        "action": action_url(f"games:{act}_playthrough", run.pk, origin=origin),
        "csrf_token": csrf_token,
    }
