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


def refund_owns_the_end(library: UserLibrary, purchase: Purchase) -> bool:
    """Whether this refund wrote the copy's end.

    The end directly follows a refund statement or correction of
    this purchase, under the same idempotency key. Adjacency
    keeps a writer that reuses one key across appends from
    lending a hand end to the refund.
    """
    end = latest_end_act(library, purchase.entry_id)
    if end is None or end.event_type not in END_STATEMENTS:
        return False
    return LibraryEvent.objects.filter(
        library=require_library(library),
        stream_id=end.stream_id,
        sequence=end.sequence - 1,
        aggregate_id=purchase.pk,
        event_type__in=_REFUND_STATEMENTS,
        idempotency_key=end.idempotency_key,
    ).exists()
