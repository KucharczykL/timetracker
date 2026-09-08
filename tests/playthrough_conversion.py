"""The runs a conversion adds at one game.

#1015 takes the provenance bridge out, so a test that
converts legacy rows reads the runs it gained instead of
asking which row each one came from. Tracking states a run
of its own, so the game holds one before the pass begins.
"""

from django.db.models import QuerySet

from games.backfill.playthrough import convert_library
from games.models import Game, Playthrough, PlaythroughKind, UserLibrary


def _live_ordinary_runs(library: UserLibrary, game: Game) -> QuerySet[Playthrough]:
    """This game's live ordinary runs, oldest first."""
    return Playthrough.objects.filter(
        library=library,
        player_game__game=game,
        removed_at__isnull=True,
        kind=PlaythroughKind.ORDINARY,
    ).order_by("created_at", "id")


def convert_and_take_runs(library: UserLibrary, game: Game) -> list[Playthrough]:
    """Convert the library, and answer the runs it added.

    In the order the rows were written: a converted run is
    keyed on its row's own instant.
    """
    before = set(_live_ordinary_runs(library, game).values_list("pk", flat=True))
    convert_library(library)
    return list(_live_ordinary_runs(library, game).exclude(pk__in=before))
