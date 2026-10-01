"""The purchases a library holds."""

from games.models import Purchase, PurchaseQuerySet, UserLibrary
from games.reads.unscoped import require_library


def library_purchases(library: UserLibrary) -> PurchaseQuerySet:
    """Live purchases; six marks, three libraries."""
    library = require_library(library)
    return Purchase.objects.filter(
        library=library,
        entry__library=library,
        entry__player_game__library=library,
        removed_at__isnull=True,
        entry__removed_at__isnull=True,
        entry__player_game__removed_at__isnull=True,
        entry__release__removed_at__isnull=True,
        entry__release__edition__removed_at__isnull=True,
        entry__release__edition__game__removed_at__isnull=True,
    )


def readable_purchases(library: UserLibrary) -> PurchaseQuerySet:
    """The row path the API serves."""
    return library_purchases(library).select_related(
        "entry__player_game__game", "entry__release__platform"
    )
