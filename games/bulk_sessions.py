"""The rows every session act reads, and one sentence.

Here rather than beside one act: an act importing a sibling closes a
cycle. The table imports each act at its foot, so an act reached first
runs that foot before its own body, and the sibling finds nothing.
"""

import uuid
from collections.abc import Sequence

from django.contrib.auth.models import User
from django.db.models import QuerySet

from common.components.primitives import Cell
from games.bulk_actions import FilterJson, Presentations, Refused, Resolution
from games.bulk_narrowing import narrowed
from games.events.dispatch import RowNotHeld, RowUnreadable
from games.filters import parse_session_filter
from games.models import PlayerSession, UserLibrary
from games.reads.player_sessions import library_sessions
from games.reads.session_run_labels import every_run_label
from games.writes.answers import answered

SESSION_GONE = "One of the sessions is no longer available, so it was left as it is."


def lost(
    keys: Sequence[uuid.UUID], found: set[uuid.UUID], sentence: str
) -> list[Refused]:
    """Gone since the confirmation, or never this library's."""
    return [Refused(str(key), sentence, lost=True) for key in keys if key not in found]


def session_scope(
    library: UserLibrary, filter_json: FilterJson
) -> QuerySet[PlayerSession]:
    return narrowed(
        library_sessions(library), library, filter_json, parse_session_filter
    )


def session_resolution(
    library: UserLibrary, keys: Sequence[uuid.UUID]
) -> Resolution[PlayerSession]:
    wanted = list(dict.fromkeys(keys))
    rows = tuple(
        library_sessions(library)
        .filter(pk__in=wanted)
        .select_related("playthrough__player_game__game", "device")
        .order_by("-sort_instant", "id")
    )
    return Resolution(rows, tuple(lost(wanted, {row.pk for row in rows}, SESSION_GONE)))


#: The attribute the labelled resolve stamps.
RUN_LABEL_ATTRIBUTE = "run_label"


def labelled_session_resolution(
    library: UserLibrary, keys: Sequence[uuid.UUID]
) -> Resolution[PlayerSession]:
    """Keys to rows, each naming its run.

    `display_name` raises for a blank-named run with no
    display number, and a session's own run never has one:
    the number is counted across a game's live ordinary runs.
    A cell that called it would answer a 500 instead.
    """
    resolution = session_resolution(library, keys)
    labels = every_run_label(library, resolution.rows)
    for row in resolution.rows:
        setattr(row, RUN_LABEL_ATTRIBUTE, labels.get(row.playthrough_id))
    return resolution


def run_label(row: PlayerSession) -> str:
    """What the row's run is called."""
    label = getattr(row, RUN_LABEL_ATTRIBUTE, None)
    if label is None:
        raise RowUnreadable(
            f"PlayerSession {row.pk} of library {row.library_id} reached the "
            "preview with no run label. The label comes from every_run_label, "
            "which names a game's live ordinary runs and its buckets in one "
            "read for the whole set; a row that arrives without one came from "
            "another resolve."
        )
    return label


def run_label_cell(row: PlayerSession, _presentations: Presentations) -> Cell:
    return run_label(row)


def session_of(actor: User, session_id: uuid.UUID) -> PlayerSession:
    """The row an Undo speaks about.

    The plain manager: `library_sessions` reads the catalog mark, and a
    session whose catalog game went is still this library's to unwind.
    """
    with answered("session"):
        row = (
            PlayerSession.objects.filter(library=actor.library, pk=session_id)
            .select_related("playthrough")
            .first()
        )
        if row is None:
            raise RowNotHeld(
                f"PlayerSession {session_id} is not library {actor.library.pk}'s, "
                "so the batch's inverse has no row to state a fact about."
            )
        return row


def device_cell(row: PlayerSession, _presentations: Presentations) -> Cell:
    return row.device.name if row.device is not None else "No device"
