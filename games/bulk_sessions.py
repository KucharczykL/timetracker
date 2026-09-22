"""The session rows every session act reads, and the sentence for a key gone.

Here rather than beside one act: two acts read the same scope, and an act
importing another act's module closes a cycle. The act table imports each act
at its foot, so an act reached first — a view importing `games.bulk_removal`,
say — runs the table's foot before its own body, and the sibling that reads a
name off it finds nothing defined.
"""

import uuid
from collections.abc import Sequence

from django.db.models import QuerySet

from games.bulk_actions import FilterJson, Refused, Resolution
from games.bulk_narrowing import narrowed
from games.filters import parse_session_filter
from games.models import PlayerSession, UserLibrary
from games.reads.player_sessions import library_sessions

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
