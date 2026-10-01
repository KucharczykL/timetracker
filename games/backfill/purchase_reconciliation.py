"""What the purchase conversion moved, checked."""

import dataclasses
import uuid
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, NamedTuple, cast

from django.db.models import Model, QuerySet, Sum
from django.utils import timezone

from games.backfill.purchase import ORIGIN, LibraryConversion
from games.backfill.purchase_plan import (
    AccessAndFormat,
    Category,
    CurrencyCode,
    LegacyRow,
    quantized_amount,
)
from games.models import (
    LibraryEntry,
    LibraryEvent,
    Purchase,
    PurchaseValuation,
    UserLibrary,
)
from games.reads.playtime import played_years
from games.views.stats_data import compute_stats

SNAPSHOT_FORMAT = 1
ALL_TIME = "all-time"

type LegacyKeyText = str  # a legacy purchase's key
type ReviewLists = dict[Category, list[LegacyKeyText]]


@dataclasses.dataclass(frozen=True, slots=True)
class CurrencyTotal:
    """One currency's legacy and converted sums."""

    currency: CurrencyCode
    legacy: Decimal
    converted: Decimal
    #: Quantized amounts less exact ones.
    quantization: Decimal
    #: Amounts of copies the pass skipped.
    skipped: Decimal

    @property
    def unexplained(self) -> Decimal:
        return self.legacy + self.quantization - self.skipped - self.converted


class Tally(NamedTuple):
    """A count the legacy rows predict."""

    expected: int
    actual: int

    @property
    def differs(self) -> bool:
        return self.expected != self.actual


class ValuationTotal(NamedTuple):
    """Legacy converted sum beside the seeded one."""

    legacy: Decimal
    seeded: Decimal


@dataclasses.dataclass(frozen=True, slots=True)
class Reconciliation:
    """Legacy rows beside what the pass stated."""

    planned_copies: int
    own_copies: int
    purchases: int
    skipped: int
    unvalued: int
    totals: tuple[CurrencyTotal, ...]
    refunded_purchases: Tally
    refund_ended_copies: Tally
    copies_by_access: Mapping[AccessAndFormat, int]
    valuations: Mapping[CurrencyCode, ValuationTotal]

    def failures(self) -> list[str]:
        """Differences no rule explains."""
        failures = [
            f"{total.currency}: legacy {total.legacy} + quantization "
            f"{total.quantization} - skipped {total.skipped} is not the "
            f"converted {total.converted}"
            for total in self.totals
            if total.unexplained != 0
        ]
        if self.refunded_purchases.differs:
            failures.append(
                f"{self.refunded_purchases.actual} refunded purchases, expected "
                f"{self.refunded_purchases.expected}"
            )
        if self.refund_ended_copies.differs:
            failures.append(
                f"{self.refund_ended_copies.actual} copies ended as refunded, "
                f"expected {self.refund_ended_copies.expected}"
            )
        return failures


def _exact(price: float) -> Decimal:
    return Decimal(repr(price))


def reconcile(
    rows: Sequence[LegacyRow], conversion: LibraryConversion
) -> Reconciliation:
    """Read the projections against the legacy rows."""
    copies = conversion.copies
    purchase_ids = [copy.purchase_id for copy in copies if copy.purchase_id]
    own_copies = [copy.entry_id for copy in copies if copy.own_copy]
    planned = [
        *(copy.planned for copy in copies),
        *(skip.planned for skip in conversion.skipped),
    ]

    legacy: defaultdict[CurrencyCode, Decimal] = defaultdict(Decimal)
    quantization: defaultdict[CurrencyCode, Decimal] = defaultdict(Decimal)
    skipped: defaultdict[CurrencyCode, Decimal] = defaultdict(Decimal)
    #: Per row: a bundle's price counts once.
    priced = {copy.row.id: copy for copy in planned if copy.price.amount is not None}
    for copy in priced.values():
        #: A row holds one currency.
        exact = _exact(copy.row.price)
        legacy[copy.price.currency] += exact
        quantization[copy.price.currency] += quantized_amount(copy.row.price) - exact
    for skip in conversion.skipped:
        if skip.planned.price.amount is not None:
            skipped[skip.planned.price.currency] += skip.planned.price.amount
    converted = dict(
        Purchase.objects.filter(pk__in=purchase_ids, amount__isnull=False)
        .values("currency")
        .annotate(total=Sum("amount"))
        .values_list("currency", "total")
    )
    totals = tuple(
        CurrencyTotal(
            currency,
            legacy[currency],
            converted.get(currency, Decimal(0)),
            quantization[currency],
            skipped[currency],
        )
        for currency in sorted(set(legacy) | set(converted))
    )

    refunded = [copy for copy in copies if copy.planned.refunded is not None]
    entries = LibraryEntry.objects.filter(pk__in=own_copies)

    valued = dict(
        PurchaseValuation.objects.filter(purchase_id__in=purchase_ids)
        .values("target_currency")
        .annotate(total=Sum("amount"))
        .values_list("target_currency", "total")
    )
    unvalued = {item.purchase_id for item in conversion.unvalued}
    legacy_converted: defaultdict[CurrencyCode, Decimal] = defaultdict(Decimal)
    for stated in copies:
        share = stated.planned.converted
        if (
            stated.purchase_id is not None
            and stated.purchase_id not in unvalued
            and share is not None
            and share.amount is not None
        ):
            legacy_converted[share.currency] += share.amount

    return Reconciliation(
        planned_copies=len(planned),
        own_copies=len(own_copies),
        purchases=len(purchase_ids),
        skipped=len(conversion.skipped),
        unvalued=len(conversion.unvalued),
        totals=totals,
        refunded_purchases=Tally(
            sum(1 for copy in refunded if copy.purchase_id is not None),
            Purchase.objects.filter(
                pk__in=purchase_ids, refund_recorded_at__isnull=False
            ).count(),
        ),
        refund_ended_copies=Tally(
            sum(1 for copy in refunded if copy.own_copy),
            entries.filter(access_end_way="refunded").count(),
        ),
        copies_by_access=dict(
            sorted(
                Counter(
                    cast(
                        list[AccessAndFormat],
                        list(entries.values_list("access", "format")),
                    )
                ).items()
            )
        ),
        valuations={
            target: ValuationTotal(
                legacy_converted.get(target, Decimal(0)),
                valued.get(target, Decimal(0)),
            )
            for target in sorted(set(valued) | set(legacy_converted))
        },
    )


def review_lists(library: UserLibrary, conversion: LibraryConversion) -> ReviewLists:
    """Legacy keys per review category."""
    listed: defaultdict[Category, set[LegacyKeyText]] = defaultdict(set)
    for metadata in LibraryEvent.objects.filter(
        library=library, source_metadata__origin=ORIGIN
    ).values_list("source_metadata", flat=True):
        for category in metadata.get("review", []):
            listed[Category(category)].update(metadata.get("legacy_purchases", []))
    for skip in conversion.skipped:
        listed[Category.SKIPPED_REMOVED_GAME].add(str(skip.legacy_id))
    return {category: sorted(listed[category]) for category in sorted(listed)}


def snapshot_value(value: object) -> Any:
    """JSON for one statistics value."""
    match value:
        case None | bool() | int() | float() | str():
            return value
        case Decimal():
            return str(value)
        case uuid.UUID():
            return str(value)
        case datetime() | date():
            return value.isoformat()
        case timedelta():
            return int(value.total_seconds())
        case QuerySet():
            return [str(key) for key in value.values_list("pk", flat=True)]
        case Model():
            return str(value.pk)
        case tuple() if hasattr(value, "_fields"):
            return {
                name: snapshot_value(getattr(value, name))
                for name in value._fields  # type: ignore[attr-defined]
            }
        case Mapping():
            return {str(key): snapshot_value(item) for key, item in value.items()}
        case list() | tuple() | set() | frozenset() | range():
            return [snapshot_value(item) for item in value]
        case _ if dataclasses.is_dataclass(value) and not isinstance(value, type):
            return {
                field.name: snapshot_value(getattr(value, field.name))
                for field in dataclasses.fields(value)
            }
    raise TypeError(f"No snapshot spelling for {type(value).__name__}.")


def snapshot_scopes(
    library: UserLibrary, rows: Sequence[LegacyRow]
) -> list[int | None]:
    """All-time, then each played or purchase year."""
    years = set(played_years(library))
    for row in rows:
        years.add(row.date_purchased.year)
        if row.date_refunded is not None:
            years.add(row.date_refunded.year)
    return [None, *sorted(years)]


def legacy_statistics(
    library: UserLibrary, rows: Sequence[LegacyRow]
) -> dict[str, Any]:
    """Every StatsData scope, before the cutover."""
    return {
        "format": SNAPSHOT_FORMAT,
        "library": str(library.pk),
        "taken_at": timezone.now().isoformat(),
        "scopes": {
            ALL_TIME if scope is None else str(scope): snapshot_value(
                compute_stats(library, scope)
            )
            for scope in snapshot_scopes(library, rows)
        },
    }
