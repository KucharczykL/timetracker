"""The entries a library holds."""

import uuid

from games.commands.endpoint import WayActStatement
from games.end_ways import EndWay
from games.events.libraryentry import ENTRY_ACCESS_END_EVENTS
from games.models import (
    Game,
    LibraryEntry,
    LibraryEntryQuerySet,
    LibraryEvent,
    UserLibrary,
)
from games.reads.unscoped import require_library


def library_entries(library: UserLibrary) -> LibraryEntryQuerySet:
    """Live entries; five marks, two libraries."""
    library = require_library(library)
    return LibraryEntry.objects.filter(
        library=library,
        player_game__library=library,
        removed_at__isnull=True,
        player_game__removed_at__isnull=True,
        release__removed_at__isnull=True,
        release__edition__removed_at__isnull=True,
        release__edition__game__removed_at__isnull=True,
    )


def readable_entries(library: UserLibrary) -> LibraryEntryQuerySet:
    """The row path the API serves."""
    return library_entries(library).select_related(
        "player_game__game", "release__platform"
    )


def game_entries(library: UserLibrary, game: Game) -> LibraryEntryQuerySet:
    """The live entries at one game."""
    return library_entries(library).filter(player_game__game=game)


def taken_back_end(library: UserLibrary, entry_id: uuid.UUID) -> WayActStatement | None:
    """The end a copy's latest resume took back, as it stood."""
    latest = (
        LibraryEvent.objects.filter(
            library=require_library(library),
            aggregate_id=entry_id,
            event_type__in=(
                ENTRY_ACCESS_END_EVENTS.stated.event_type,
                ENTRY_ACCESS_END_EVENTS.corrected.event_type,
            ),
        )
        .order_by("-sequence")
        .first()
    )
    if latest is None:
        return None
    return WayActStatement(
        latest.effective_time, EndWay(latest.payload["way"]), latest.payload["note"]
    )
