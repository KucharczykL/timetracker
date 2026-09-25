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
from games.events.dispatch import RowNotHeld
from games.filters import parse_session_filter
from games.models import PlayerSession, UserLibrary
from games.reads.player_sessions import library_sessions
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
