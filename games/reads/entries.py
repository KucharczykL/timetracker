"""The entries a library holds."""

from games.models import Game, LibraryEntry, LibraryEntryQuerySet, UserLibrary
from games.reads.unscoped import require_library


def library_entries(library: UserLibrary) -> LibraryEntryQuerySet:
    """Every live entry this library holds.

    Five marks: the entry's, its tracked game's, and the three
    catalog rows' above the Release. The tracked game's library
    is stated too: it can name another library's row.
    """
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
    """The row path the API serves: game, Release, platform."""
    return library_entries(library).select_related(
        "player_game__game", "release__platform"
    )


def game_entries(library: UserLibrary, game: Game) -> LibraryEntryQuerySet:
    """The live entries at one game."""
    return library_entries(library).filter(player_game__game=game)
