"""The entries a library holds."""

import uuid
from collections import defaultdict
from collections.abc import Iterable
from typing import NamedTuple

from django.db.models import F, QuerySet

from games.commands.endpoint import WayActStatement
from games.end_ways import EndWay
from games.endpoints import ENTRY_ACCESS_END
from games.events.libraryentry import ENTRY_ACCESS_END_EVENTS
from games.models import (
    EntryAccess,
    EntryFormat,
    Game,
    LibraryEntry,
    LibraryEntryQuerySet,
    LibraryEvent,
    UserLibrary,
)
from games.reads.endpoints import StatedEndpoint, stated
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


#: A position in a library's event stream.
type EventSequence = int

END_STATEMENTS = (
    ENTRY_ACCESS_END_EVENTS.stated.event_type,
    ENTRY_ACCESS_END_EVENTS.corrected.event_type,
)


def _newest_events(library: UserLibrary, entry_id: uuid.UUID) -> QuerySet[LibraryEvent]:
    return LibraryEvent.objects.filter(
        library=require_library(library), aggregate_id=entry_id
    ).order_by("-sequence")


def latest_end_act(library: UserLibrary, entry_id: uuid.UUID) -> LibraryEvent | None:
    """The copy's latest end-family event."""
    return (
        _newest_events(library, entry_id)
        .filter(
            event_type__in=(
                *END_STATEMENTS,
                ENTRY_ACCESS_END_EVENTS.voided.event_type,
                ENTRY_ACCESS_END_EVENTS.resumed.event_type,
            )
        )
        .first()
    )


def taken_back_end(
    library: UserLibrary, entry_id: uuid.UUID, *, resumed_at: EventSequence
) -> WayActStatement | None:
    """The end standing before that resume."""
    standing = (
        _newest_events(library, entry_id)
        .filter(event_type__in=END_STATEMENTS, sequence__lt=resumed_at)
        .first()
    )
    if standing is None:
        return None
    return WayActStatement(
        standing.effective_time,
        EndWay(standing.payload["way"]),
        standing.payload["note"],
    )


#: A catalog game's key.
type GameId = uuid.UUID


def copy_end(entry: LibraryEntry) -> StatedEndpoint | None:
    """The copy's standing end; None while held."""
    return stated(entry, ENTRY_ACCESS_END)


class EndedCopy(NamedTuple):
    entry: LibraryEntry
    end: StatedEndpoint


class AccessSummary(NamedTuple):
    """One game's live copies, for its badge."""

    #: Held copies, earliest acquired first.
    held: tuple[LibraryEntry, ...]
    #: Latest end first.
    ended: tuple[EndedCopy, ...]

    @property
    def owned_now(self) -> bool:
        return any(entry.access == EntryAccess.OWNED for entry in self.held)

    @property
    def former(self) -> EndedCopy | None:
        """Nothing held: the latest-ended copy."""
        if self.held or not self.ended:
            return None
        return self.ended[0]

    @property
    def shown(self) -> tuple[LibraryEntry, ...]:
        """Held copies, else the former one."""
        former = self.former
        return self.held if former is None else (former.entry,)

    @property
    def formats(self) -> frozenset[EntryFormat]:
        return frozenset(EntryFormat(entry.format) for entry in self.shown)


def access_summaries(
    library: UserLibrary, game_ids: Iterable[GameId]
) -> dict[GameId, AccessSummary]:
    """One summary per game; one query."""
    held: dict[GameId, list[LibraryEntry]] = defaultdict(list)
    ended: dict[GameId, list[EndedCopy]] = defaultdict(list)
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
        end = copy_end(entry)
        if end is None:
            held[game_id].append(entry)
        else:
            ended[game_id].append(EndedCopy(entry, end))
    return {
        game_id: AccessSummary(tuple(held[game_id]), tuple(ended[game_id]))
        for game_id in held.keys() | ended.keys()
    }
