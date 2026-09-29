"""The entries a library holds."""

import uuid
from collections import defaultdict
from collections.abc import Iterable
from typing import NamedTuple

from django.db.models import F

from games.commands.endpoint import WayActStatement
from games.end_ways import EndWay
from games.events.libraryentry import ENTRY_ACCESS_END_EVENTS
from games.models import (
    EntryAccess,
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


#: A catalog game's key.
type GameId = uuid.UUID


class AccessSummary(NamedTuple):
    """What one game's live copies say, for its badge."""

    #: Copies no end stands on, earliest acquired first.
    held: tuple[LibraryEntry, ...]
    #: With nothing held, the copy whose end is latest.
    former: LibraryEntry | None

    @property
    def owned_now(self) -> bool:
        return any(entry.access == EntryAccess.OWNED for entry in self.held)

    @property
    def formats(self) -> frozenset[str]:
        return frozenset(entry.format for entry in self.held)


def access_summaries(
    library: UserLibrary, game_ids: Iterable[GameId]
) -> dict[GameId, AccessSummary]:
    """One summary per game holding a live copy; one query."""
    held: dict[GameId, list[LibraryEntry]] = defaultdict(list)
    former: dict[GameId, LibraryEntry] = {}
    rows = (
        library_entries(library)
        .filter(player_game__game_id__in=list(game_ids))
        .select_related("player_game")
        .order_by(
            F("access_ended_upper").desc(nulls_last=True),
            F("access_end_recorded_at").desc(),
            "acquired_lower",
            "id",
        )
    )
    for entry in rows:
        game_id = entry.player_game.game_id
        if entry.access_end_recorded_at is None:
            held[game_id].append(entry)
        else:
            former.setdefault(game_id, entry)
    return {
        game_id: AccessSummary(
            tuple(held[game_id]), None if held[game_id] else former[game_id]
        )
        for game_id in held.keys() | former.keys()
    }
