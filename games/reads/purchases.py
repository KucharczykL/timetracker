"""The purchases a library holds."""

from games.events.purchase import PURCHASE_REFUND_EVENTS
from games.models import LibraryEvent, Purchase, PurchaseQuerySet, UserLibrary
from games.reads.entries import END_STATEMENTS, latest_end_act
from games.reads.unscoped import require_library

_REFUND_STATEMENTS = (
    PURCHASE_REFUND_EVENTS.stated.event_type,
    PURCHASE_REFUND_EVENTS.corrected.event_type,
)


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
    return library_purchases(library).select_related("entry__player_game__game")


def coupled_end(library: UserLibrary, purchase: Purchase) -> LibraryEvent | None:
    """The copy's standing end, where the refund wrote it.

    Its dispatch appended a refund statement or correction of
    this purchase: one idempotency key per dispatch.
    """
    end = latest_end_act(library, purchase.entry_id)
    if end is None or end.event_type not in END_STATEMENTS:
        return None
    refund_beside_it = LibraryEvent.objects.filter(
        library=require_library(library),
        aggregate_id=purchase.pk,
        event_type__in=_REFUND_STATEMENTS,
        idempotency_key=end.idempotency_key,
    ).exists()
    return end if refund_beside_it else None
