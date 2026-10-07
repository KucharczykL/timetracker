"""What Game detail's Library note counts."""

from games.filters import LibraryEntryFilter, PurchaseFilter
from games.models import Game, UserLibrary
from games.reads.purchase_figures import purchases_matching


def previous_copies_filter(game: Game) -> LibraryEntryFilter:
    """The game's copies no longer had."""
    return LibraryEntryFilter.where(game=[game.pk], is_ended=True)


def previous_copy_purchases_filter(game: Game) -> PurchaseFilter:
    """Purchases of copies no longer had."""
    purchases = PurchaseFilter.where(game=[game.pk])
    purchases.entry_filter = LibraryEntryFilter.where(is_ended=True)
    return purchases


def refunded_held_purchases_filter(game: Game) -> PurchaseFilter:
    """Refunded purchases of copies had now."""
    purchases = PurchaseFilter.where(game=[game.pk], is_refunded=True)
    purchases.entry_filter = LibraryEntryFilter.where(is_ended=False)
    return purchases


def purchase_count(library: UserLibrary, purchase_filter: PurchaseFilter) -> int:
    return purchases_matching(library, purchase_filter).count()
