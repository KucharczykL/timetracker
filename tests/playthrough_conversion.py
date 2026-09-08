"""The runs a conversion adds here.

No bridge maps a row to its run, so a test reads what the
pass added. Tracking states a run before it begins.
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
    """Convert the library, answer the runs added.

    In the order the rows were written: a converted run is
    keyed on its row's instant.
    """
    before = set(_live_ordinary_runs(library, game).values_list("pk", flat=True))
    convert_library(library)
    return list(_live_ordinary_runs(library, game).exclude(pk__in=before))
