"""A purchase's amount in the reporting currency."""

from collections.abc import Iterable
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import NamedTuple
from uuid import UUID

from games.models import PurchaseValuation, UserLibrary

CENT = Decimal("0.01")
#: Exact for every storable amount and rate.
PRODUCT_PRECISION = 60


class ValuationInput(NamedTuple):
    """What a valuation is computed from."""

    purchase_id: UUID
    amount: Decimal
    currency: str
    rate_year: int


def needs_rate(facts: ValuationInput, target: str) -> bool:
    """A purchase in another currency, not free."""
    return facts.currency != target and facts.amount != 0


def value(
    facts: ValuationInput,
    target: str,
    rate: Decimal | None,
    *,
    version: int,
    calculated_at: datetime,
) -> PurchaseValuation:
    """One unsaved valuation, rounded half up once."""
    if needs_rate(facts, target) != (rate is not None):
        raise ValueError(
            f"Purchase {facts.purchase_id} in {facts.currency} to {target} "
            f"takes {'a' if needs_rate(facts, target) else 'no'} rate."
        )
    if rate is None:
        amount = facts.amount
    else:
        with localcontext(prec=PRODUCT_PRECISION):
            amount = facts.amount * rate
    return PurchaseValuation(
        purchase_id=facts.purchase_id,
        target_currency=target,
        amount=amount.quantize(CENT, rounding=ROUND_HALF_UP),
        source_amount=facts.amount,
        source_currency=facts.currency,
        rate_year=facts.rate_year,
        rate=rate,
        version=version,
        calculated_at=calculated_at,
    )


def publish_valuations(
    library: UserLibrary, valuations: Iterable[PurchaseValuation]
) -> None:
    """Replace the library's valuations whole.

    The caller holds the transaction and the conversion state's lock.
    """
    PurchaseValuation.objects.filter(library=library).delete()
    rows = list(valuations)
    for row in rows:
        row.library = library
    PurchaseValuation.objects.bulk_create(rows)
