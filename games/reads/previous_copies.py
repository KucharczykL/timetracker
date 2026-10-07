"""What Game detail's Library note counts."""

from dataclasses import replace

from games.filters import LibraryEntryFilter, PurchaseFilter
from games.models import Game, UserLibrary
from games.reads.purchase_figures import purchases_matching


def previous_copies_filter(game: Game) -> LibraryEntryFilter:
    """The game's copies no longer had."""
    return LibraryEntryFilter.where(game=[game.pk], is_ended=True)


def previous_copy_purchases_filter(game: Game) -> PurchaseFilter:
    """Purchases of copies no longer had."""
    return replace(
        PurchaseFilter.where(game=[game.pk]),
        entry_filter=LibraryEntryFilter.where(is_ended=True),
    )


def refunded_held_purchases_filter(game: Game) -> PurchaseFilter:
    """Refunded purchases of copies had now."""
    return replace(
        PurchaseFilter.where(game=[game.pk], is_refunded=True),
        entry_filter=LibraryEntryFilter.where(is_ended=False),
    )


def purchase_count(library: UserLibrary, purchase_filter: PurchaseFilter) -> int:
    """Counted over the Purchases list's base."""
    return purchases_matching(library, purchase_filter).count()
