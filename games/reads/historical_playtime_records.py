"""The records a library counts, and the row path a page reads."""

from django.db.models import F

from games.models import (
    Game,
    HistoricalPlaytime,
    HistoricalPlaytimeQuerySet,
    UserLibrary,
)

#: Newest first; an unknown `when` last; then newest recorded.
RECORD_ORDER = (F("when_lower").desc(nulls_last=True), "-created_at", "id")


def library_records(library: UserLibrary) -> HistoricalPlaytimeQuerySet:
    """Every live record this library counts.

    A copy of this breaks quietly. The record's and its tracked
    game's libraries are both stated: either can name another
    library's row. `alive()` alone keeps the records of a removed
    catalog game.
    """
    return HistoricalPlaytime.objects.filter(
        library=library,
        player_game__library=library,
        removed_at__isnull=True,
        player_game__removed_at__isnull=True,
        player_game__game__removed_at__isnull=True,
    )


def readable_records(library: UserLibrary) -> HistoricalPlaytimeQuerySet:
    """The row path the list, the section and the API share."""
    return library_records(library).select_related(
        "player_game__game__platform", "device"
    )


def game_records(library: UserLibrary, game: Game) -> HistoricalPlaytimeQuerySet:
    """The counted records at one catalog game."""
    return library_records(library).filter(player_game__game=game)
