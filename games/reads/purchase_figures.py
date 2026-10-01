"""The statistics' purchase figures.

Each figure states one `PurchaseFilter`, which its link
carries too, so a figure and its link compile one predicate.
A purchased day is in a year by containment.
"""

from decimal import Decimal
from typing import NamedTuple

from django.db.models import Count, Max, Q, QuerySet, Sum

from games.filters import (
    PurchaseFilter,
    filter_query_context_for_library,
    filter_queryset_for_library,
)
from games.models import PriceState, Purchase, UserLibrary
from games.reads.days import YearScope
from games.valuations import CurrencyCode


def _bounds(year: YearScope) -> dict[str, tuple[str, str]]:
    if year is None:
        return {}
    return {"purchased__within": (f"{year}-01-01", f"{year}-12-31")}


def purchases_in_scope(year: YearScope) -> PurchaseFilter:
    """Every purchase bought in scope."""
    return PurchaseFilter.where(**_bounds(year))


def refunded_in_scope(year: YearScope) -> PurchaseFilter:
    return PurchaseFilter.where(is_refunded=True, **_bounds(year))


def unrefunded_in_scope(year: YearScope) -> PurchaseFilter:
    return PurchaseFilter.where(is_refunded=False, **_bounds(year))


def unpriced_in_scope(year: YearScope) -> PurchaseFilter:
    """Unrefunded, at a price nobody knows."""
    return PurchaseFilter.where(
        is_refunded=False, price_state=[PriceState.UNKNOWN], **_bounds(year)
    )


def unvalued_in_scope(year: YearScope) -> PurchaseFilter:
    """Unrefunded, an amount and no valuation."""
    return PurchaseFilter.where(
        is_refunded=False,
        amount__notnull=True,
        valuation__isnull=True,
        **_bounds(year),
    )


def purchases_matching(
    library: UserLibrary, purchase_filter: PurchaseFilter
) -> QuerySet[Purchase]:
    """The Purchases list's base, narrowed."""
    context = filter_query_context_for_library(library)
    return filter_queryset_for_library("purchase", library).filter(
        purchase_filter.to_q(context)
    )


class PurchaseFigures(NamedTuple):
    """One scope's purchase figures."""

    purchases: int
    refunded: int
    #: Current valuations of unrefunded purchases.
    total_spent: Decimal
    #: Unrefunded purchases with a valuation.
    valued: int
    unpriced: int
    unvalued: int
    #: Read beside the total; none without rows.
    currency: CurrencyCode | None


def purchase_figures(library: UserLibrary, year: YearScope) -> PurchaseFigures:
    """Every figure, one statement."""
    rows = purchases_matching(library, purchases_in_scope(year))
    unrefunded = Q(refund_recorded_at__isnull=True)
    valued = unrefunded & Q(valuation_amount__isnull=False)
    totals = rows.aggregate(
        count=Count("pk"),
        refunded=Count("pk", filter=~unrefunded),
        total_spent=Sum("valuation_amount", filter=unrefunded),
        valued=Count("pk", filter=valued),
        unpriced=Count("pk", filter=unrefunded & Q(amount__isnull=True)),
        unvalued=Count(
            "pk",
            filter=unrefunded
            & Q(amount__isnull=False)
            & Q(valuation_amount__isnull=True),
        ),
        #: One statement, so total and currency agree.
        currency=Max("valuation_currency"),
    )
    return PurchaseFigures(
        purchases=totals["count"],
        refunded=totals["refunded"],
        total_spent=totals["total_spent"] or Decimal(0),
        valued=totals["valued"],
        unpriced=totals["unpriced"],
        unvalued=totals["unvalued"],
        currency=totals["currency"],
    )
