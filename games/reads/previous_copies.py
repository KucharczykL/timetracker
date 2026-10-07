"""What Game detail's Library note counts."""

from games.filters import LibraryEntryFilter, PurchaseFilter
from games.models import Game, UserLibrary
from games.reads.purchase_figures import purchases_matching


def previous_copies_filter(game: Game) -> LibraryEntryFilter:
    """The game's copies no longer had."""
    return LibraryEntryFilter.where(game=[game.pk], is_ended=True)


def previous_purchases_filter(game: Game) -> PurchaseFilter:
    """The game's purchases no card shows."""
    purchases = PurchaseFilter.where(game=[game.pk])
    #: Nested: a node's OR follows its criteria.
    purchases.AND = [
        PurchaseFilter(
            OR=[
                PurchaseFilter.where(is_refunded=True),
                PurchaseFilter(entry_filter=LibraryEntryFilter.where(is_ended=True)),
            ]
        )
    ]
    return purchases


def previous_purchase_count(library: UserLibrary, game: Game) -> int:
    return purchases_matching(library, previous_purchases_filter(game)).count()
