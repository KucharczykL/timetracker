"""What the Library tab's acts share."""

import uuid
from collections.abc import Sequence

from django.contrib.auth.models import User
from django.db.models import QuerySet

from games.bulk_actions import FilterJson, PreviewColumn, Resolution
from games.bulk_narrowing import narrowed
from games.bulk_sessions import lost
from games.events.dispatch import RowNotHeld
from games.filters import parse_entry_filter
from games.models import EntryAccess, EntryFormat, LibraryEntry, UserLibrary
from games.reads.entries import library_entries
from games.reads.releases import platform_words
from games.writes.answers import answered
from games.writes.libraryentry import SUBJECT

ENTRY_GONE = "One of the copies is no longer available, so it was left as it is."


def entry_scope(
    library: UserLibrary, filter_json: FilterJson
) -> QuerySet[LibraryEntry]:
    """The list's own read."""
    return narrowed(library_entries(library), library, filter_json, parse_entry_filter)


def entry_resolution(
    library: UserLibrary, keys: Sequence[uuid.UUID]
) -> Resolution[LibraryEntry]:
    """Live copies, with game and platform."""
    wanted = list(dict.fromkeys(keys))
    rows = tuple(
        library_entries(library)
        .filter(pk__in=wanted)
        .select_related("player_game__game", "release__platform")
        .order_by("player_game__game__sort_name", "id")
    )
    return Resolution(rows, tuple(lost(wanted, {row.pk for row in rows}, ENTRY_GONE)))


def removed_entry(actor: User, entry_id: uuid.UUID) -> LibraryEntry:
    """An inverse's row, removed or not."""
    with answered(SUBJECT):
        entry = (
            LibraryEntry.objects.select_related("player_game__game")
            .filter(library=actor.library, pk=entry_id)
            .first()
        )
        if entry is None:
            raise RowNotHeld(
                f"LibraryEntry {entry_id} is not library {actor.library.pk}'s, "
                "so the batch's inverse has no row to state a fact about."
            )
    return entry


ENTRY_PREVIEW: tuple[PreviewColumn[LibraryEntry], ...] = (
    PreviewColumn("Game", lambda row, _: row.player_game.game.name),
    PreviewColumn("Platform", lambda row, _: platform_words(row.release)),
    PreviewColumn("Access", lambda row, _: EntryAccess(row.access).label),
    PreviewColumn("Format", lambda row, _: EntryFormat(row.format).label),
)
