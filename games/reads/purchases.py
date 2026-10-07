"""The purchases a library holds."""

import uuid
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from decimal import Decimal
from typing import Protocol
from zoneinfo import ZoneInfo

from django.db.models import (
    CharField,
    DecimalField,
    Exists,
    F,
    Func,
    IntegerField,
    OuterRef,
    Q,
    QuerySet,
    Subquery,
    Value,
)
from django.db.models.expressions import Expression
from django.db.models.functions import Coalesce, ExtractYear, NullIf

from games.endpoints import PURCHASE_REFUND
from games.events.dispatch import RowUnreadable
from games.events.libraryentry import LIBRARYENTRY_REMOVED
from games.events.purchase import PURCHASE_REFUND_EVENTS, PURCHASE_REMOVED
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
from games.reads.endpoints import stated
from games.reads.entries import END_STATEMENTS, EntryId, latest_end_act
from games.reads.playthrough_completions import (
    PURCHASE_RUNS,
    completion_exists,
    reported_completion,
    reported_completion_day,
)
from games.reads.unscoped import require_library
from games.valuations import CurrencyCode, ValuationInput
from timetracker.temporal import TemporalValue

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
    """What the task values, in key order; compared whole."""
    zone = calendar_day_zone(library)
    rows = (
        library_purchases(library)
        .filter(amount__isnull=False)
        .order_by("pk")
        .values_list("pk", "amount", "currency", valuation_year(zone))
    )
    return [
        ValuationInput(
            purchase_id=purchase_id, amount=amount, currency=currency, rate_year=year
        )
        for purchase_id, amount, currency, year in rows
    ]


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


class ValuedPurchase(Protocol):
    """A row ``with_valuation`` annotated."""

    #: Null without a current valuation.
    valuation_amount: Decimal | None
    #: The published target; null before any.
    valuation_currency: CurrencyCode | None


class UnscopedValuationRead(RuntimeError):
    """A valuation alias executed without a library."""


class UnscopedValuationAlias(Expression):
    """Resolves for validation; refuses to compile."""

    def as_sql(self, compiler, connection):
        raise UnscopedValuationRead(
            "A valuation read was executed without a library; state one."
        )


type Annotations = dict[str, Expression | Func | Subquery]


def valuation_annotations(
    library: UserLibrary | None,
) -> tuple[Annotations, Annotations]:
    """The rate year, then what reads it."""
    if library is None:
        return (
            {"rate_year": UnscopedValuationAlias(output_field=IntegerField())},
            {
                "valuation_amount": UnscopedValuationAlias(
                    output_field=DecimalField(max_digits=26, decimal_places=2)
                ),
                "valuation_currency": UnscopedValuationAlias(
                    output_field=CharField(null=True)
                ),
            },
        )
    current = current_valuation(library)
    return (
        {"rate_year": valuation_year(calendar_day_zone(library))},
        {
            "valuation_amount": Subquery(current.values("amount")[:1]),
            "valuation_currency": NullIf(_published_target(library), Value("")),
        },
    )


def with_valuation(
    purchases: PurchaseQuerySet, library: UserLibrary
) -> PurchaseQuerySet:
    """Annotate rows into ``ValuedPurchase``."""
    return purchases.annotated_for_filtering(require_library(library))


def readable_purchases(library: UserLibrary) -> PurchaseQuerySet:
    """The row path the API serves."""
    return with_valuation(
        library_purchases(library).select_related("entry__player_game__game"),
        library,
    )


def latest_refund_act(
    library: UserLibrary, purchase_id: uuid.UUID
) -> LibraryEvent | None:
    """The purchase's latest refund-family event."""
    return (
        LibraryEvent.objects.filter(
            library=require_library(library),
            aggregate_id=purchase_id,
            event_type__in=PURCHASE_REFUND_EVENTS.family,
        )
        .order_by("-sequence")
        .first()
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


#: Purchased day, unknown last, then recorded.
PURCHASE_ORDER = (F("purchased_lower").asc(nulls_last=True), "created_at", "id")


def unremoved_purchases(library: UserLibrary, entry_id: EntryId) -> PurchaseQuerySet:
    """The copy's unremoved purchases, refunded included."""
    return Purchase.objects.filter(
        library=require_library(library), entry_id=entry_id, removed_at__isnull=True
    ).order_by(*PURCHASE_ORDER)


def unremoved_purchase_ids(library: UserLibrary, entry_id: EntryId) -> list[uuid.UUID]:
    return list(unremoved_purchases(library, entry_id).values_list("pk", flat=True))


def cascaded_purchase_ids(library: UserLibrary, entry_id: EntryId) -> list[uuid.UUID]:
    """Purchases the copy's latest removal took."""
    library = require_library(library)
    removal = (
        LibraryEvent.objects.filter(
            library=library,
            aggregate_id=entry_id,
            event_type=LIBRARYENTRY_REMOVED.event_type,
        )
        .order_by("-sequence")
        .first()
    )
    if removal is None:
        #: Only its projector stamps the mark.
        raise RowUnreadable(
            f"Entry {entry_id} of library {library.pk} is removed, but its "
            "stream holds no libraryentry.removed event."
        )
    latest_removal_key = Subquery(
        LibraryEvent.objects.filter(
            library=library,
            aggregate_id=OuterRef("pk"),
            event_type=PURCHASE_REMOVED.event_type,
        )
        .order_by("-sequence")
        .values("idempotency_key")[:1]
    )
    return list(
        Purchase.objects.filter(
            library=library, entry_id=entry_id, removed_at__isnull=False
        )
        .annotate(removal_key=latest_removal_key)
        .filter(removal_key=removal.idempotency_key)
        .order_by("pk")
        .values_list("pk", flat=True)
    )


#: A purchase ``with_valuation`` annotated.
type ValuedRow = Purchase
#: Absent key means none: .get(pk, ()).
type CopyPurchases = Mapping[EntryId, Sequence[ValuedRow]]


def copy_purchases(library: UserLibrary, entry_ids: Iterable[EntryId]) -> CopyPurchases:
    """Each copy's live purchases, valued."""
    grouped: dict[EntryId, list[Purchase]] = {}
    purchases = with_valuation(
        library_purchases(library).filter(entry_id__in=list(entry_ids)), library
    ).order_by(*PURCHASE_ORDER)
    for purchase in purchases:
        grouped.setdefault(purchase.entry_id, []).append(purchase)
    return grouped


def unrefunded(purchases: Sequence[ValuedRow]) -> list[ValuedRow]:
    """The purchases no refund names."""
    return [
        purchase for purchase in purchases if stated(purchase, PURCHASE_REFUND) is None
    ]


#: What every purchase page reads.
PURCHASE_PATHS = ("entry__player_game__game", "entry__release__platform")


def purchase_list_rows(library: UserLibrary) -> PurchaseQuerySet:
    """The list's rows, carrying the Finished facts."""
    return (
        library_purchases(library)
        .annotated_for_filtering(library)
        .select_related(*PURCHASE_PATHS)
        .annotate(
            has_completion=completion_exists(library, None, PURCHASE_RUNS),
            completed_value=reported_completion(library, PURCHASE_RUNS),
            completed_day=reported_completion_day(library, PURCHASE_RUNS),
        )
    )


class ListedPurchase(ValuedPurchase, Protocol):
    """A row `purchase_list_rows` annotated."""

    has_completion: bool
    completed_value: TemporalValue | None
    completed_day: date | None
