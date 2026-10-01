"""The purchases a library holds."""

from zoneinfo import ZoneInfo

from django.db.models import Exists, F, Func, OuterRef, Q, QuerySet, Subquery
from django.db.models.functions import Coalesce, ExtractYear

from games.events.purchase import PURCHASE_REFUND_EVENTS
from games.models import (
    ExchangeRate,
    LibraryEvent,
    Purchase,
    PurchaseConversionState,
    PurchaseQuerySet,
    PurchaseValuation,
    UserLibrary,
)
from games.reads.calendar import calendar_day_zone
from games.reads.entries import END_STATEMENTS, latest_end_act
from games.reads.unscoped import require_library
from games.valuations import ValuationInput

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


def valuation_year(zone: ZoneInfo) -> Func:
    """The rate's year: purchased, else recorded."""
    return Coalesce(
        ExtractYear("purchased_lower"),
        ExtractYear("purchased_upper"),
        ExtractYear("purchase_recorded_at", tzinfo=zone),
    )


def valued_purchases(library: UserLibrary) -> PurchaseQuerySet:
    """Live purchases with an amount, and their rate year."""
    return (
        library_purchases(library)
        .filter(amount__isnull=False)
        .annotate(rate_year=valuation_year(calendar_day_zone(library)))
        .order_by("pk")
    )


def valuation_inputs(library: UserLibrary) -> list[ValuationInput]:
    """What the task values, by key."""
    zone = calendar_day_zone(library)
    rows = (
        library_purchases(library)
        .filter(amount__isnull=False)
        .order_by("pk")
        .values_list("pk", "amount", "currency", valuation_year(zone))
    )
    return [ValuationInput(*row) for row in rows]


def _published_target(library: UserLibrary) -> Subquery:
    return Subquery(
        PurchaseConversionState.objects.filter(library=library).values(
            "published_currency"
        )[:1]
    )


def current_valuation(library: UserLibrary) -> QuerySet[PurchaseValuation]:
    """The outer purchase's valuation, while current.

    The outer row must carry ``rate_year``.
    """
    needs_no_rate = Q(source_currency=F("target_currency")) | Q(source_amount=0)
    stored_rate = ExchangeRate.objects.filter(
        currency_from=OuterRef("source_currency"),
        currency_to=OuterRef("target_currency"),
        year=OuterRef("rate_year"),
    ).values("rate")[:1]
    return PurchaseValuation.objects.filter(
        library=require_library(library),
        purchase_id=OuterRef("pk"),
        target_currency=_published_target(library),
        source_amount=OuterRef("amount"),
        source_currency=OuterRef("currency"),
        rate_year=OuterRef("rate_year"),
    ).filter(
        (needs_no_rate & Q(rate__isnull=True))
        | (~needs_no_rate & Q(rate=Subquery(stored_rate)))
    )


def stale_purchases(library: UserLibrary) -> PurchaseQuerySet:
    """Valued purchases without a current valuation."""
    return valued_purchases(library).filter(~Exists(current_valuation(library)))


def with_valuation(
    purchases: PurchaseQuerySet, library: UserLibrary
) -> PurchaseQuerySet:
    """Annotate ``valuation_amount`` and ``valuation_currency``; null when stale."""
    current = current_valuation(library)
    return purchases.annotate(
        rate_year=valuation_year(calendar_day_zone(library))
    ).annotate(
        valuation_amount=Subquery(current.values("amount")[:1]),
        valuation_currency=Subquery(current.values("target_currency")[:1]),
    )


def readable_purchases(library: UserLibrary) -> PurchaseQuerySet:
    """The row path the API serves."""
    return with_valuation(
        library_purchases(library).select_related("entry__player_game__game"),
        library,
    )


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
