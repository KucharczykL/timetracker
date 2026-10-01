"""What the purchase conversion moved, checked."""

import dataclasses
import uuid
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from django.db.models import Model, QuerySet, Sum
from django.utils import timezone

from games.backfill.purchase import ORIGIN, LibraryConversion
from games.backfill.purchase_plan import Category, LegacyRow, quantized_amount
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

type CurrencyCode = str  # "EUR"
type ReviewLists = dict[str, list[str]]


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


@dataclasses.dataclass(frozen=True, slots=True)
class Reconciliation:
    """Legacy rows beside what the pass stated."""

    planned_copies: int
    copies: int
    purchases: int
    skipped: int
    totals: tuple[CurrencyTotal, ...]
    refunded_purchases_expected: int
    refunded_purchases: int
    refund_ended_copies_expected: int
    refund_ended_copies: int
    copies_by_access: Mapping[tuple[str, str], int]
    #: Target to (legacy converted, valued).
    valuations: Mapping[CurrencyCode, tuple[Decimal, Decimal]]

    def failures(self) -> list[str]:
        """Differences no rule explains."""
        failures = [
            f"{total.currency}: legacy {total.legacy} + quantization "
            f"{total.quantization} - skipped {total.skipped} is not the "
            f"converted {total.converted}"
            for total in self.totals
            if total.unexplained
        ]
        if self.refunded_purchases != self.refunded_purchases_expected:
            failures.append(
                f"{self.refunded_purchases} refunded purchases, expected "
                f"{self.refunded_purchases_expected}"
            )
        if self.refund_ended_copies != self.refund_ended_copies_expected:
            failures.append(
                f"{self.refund_ended_copies} copies ended as refunded, expected "
                f"{self.refund_ended_copies_expected}"
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

    legacy: defaultdict[CurrencyCode, Decimal] = defaultdict(Decimal)
    quantization: defaultdict[CurrencyCode, Decimal] = defaultdict(Decimal)
    skipped: defaultdict[CurrencyCode, Decimal] = defaultdict(Decimal)
    planned = [
        *(copy.planned for copy in copies),
        *(skip.planned for skip in conversion.skipped),
    ]
    priced = {copy.row.id: copy for copy in planned if copy.amount is not None}
    for copy in priced.values():
        exact = _exact(copy.row.price)
        legacy[copy.currency] += exact
        quantization[copy.currency] += quantized_amount(copy.row.price) - exact
    for skip in conversion.skipped:
        if skip.planned.amount is not None:
            skipped[skip.planned.currency] += skip.planned.amount
    converted = dict(
        Purchase.objects.filter(pk__in=purchase_ids, amount__isnull=False)
        .values("currency")
        .annotate(total=Sum("amount"))
        .values_list("currency", "total")
    )
    currencies = sorted(set(legacy) | set(converted))
    totals = tuple(
        CurrencyTotal(
            currency,
            legacy[currency],
            converted.get(currency, Decimal(0)),
            quantization[currency],
            skipped[currency],
        )
        for currency in currencies
    )

    refunded = [copy for copy in copies if copy.planned.refunded is not None]
    ended_expected = [
        copy
        for copy in refunded
        if copy.own_copy
        and (copy.planned.access != "owned" or copy.planned.kind == "game")
    ]
    entries = LibraryEntry.objects.filter(pk__in=own_copies)
    by_access = Counter(entries.values_list("access", "format"))

    valuations: dict[CurrencyCode, tuple[Decimal, Decimal]] = {}
    valued = dict(
        PurchaseValuation.objects.filter(purchase_id__in=purchase_ids)
        .values("target_currency")
        .annotate(total=Sum("amount"))
        .values_list("target_currency", "total")
    )
    legacy_converted: defaultdict[CurrencyCode, Decimal] = defaultdict(Decimal)
    for row in rows:
        if row.converted_price is not None and row.converted_currency:
            legacy_converted[row.converted_currency.strip().upper()] += _exact(
                row.converted_price
            )
    for target in sorted(set(valued) | set(legacy_converted)):
        valuations[target] = (
            legacy_converted.get(target, Decimal(0)),
            valued.get(target, Decimal(0)),
        )

    return Reconciliation(
        planned_copies=len(planned),
        copies=len(own_copies),
        purchases=len(purchase_ids),
        skipped=len(conversion.skipped),
        totals=totals,
        refunded_purchases_expected=sum(
            1 for copy in refunded if copy.purchase_id is not None
        ),
        refunded_purchases=Purchase.objects.filter(
            pk__in=purchase_ids, refund_recorded_at__isnull=False
        ).count(),
        refund_ended_copies_expected=len(ended_expected),
        refund_ended_copies=entries.filter(access_end_way="refunded").count(),
        copies_by_access=dict(sorted(by_access.items())),
        valuations=valuations,
    )


def review_lists(library: UserLibrary, conversion: LibraryConversion) -> ReviewLists:
    """Legacy keys per review category."""
    listed: defaultdict[str, set[str]] = defaultdict(set)
    for metadata in LibraryEvent.objects.filter(
        library=library, source_metadata__origin=ORIGIN
    ).values_list("source_metadata", flat=True):
        for category in metadata.get("review", []):
            listed[category].update(metadata.get("legacy_purchases", []))
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
    """All-time, then every year a record names."""
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
