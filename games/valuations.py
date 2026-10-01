"""A purchase's amount in the reporting currency."""

from collections.abc import Iterable, Mapping
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import NamedTuple
from uuid import UUID

from django.db import transaction

from games.models import PurchaseValuation, UserLibrary

type CurrencyCode = str  # "EUR"
type RateYear = int  # 2024
type ConversionVersion = int  # PurchaseConversionState.requested_version

CENT = Decimal("0.01")
#: Exact for every storable amount and rate.
PRODUCT_PRECISION = 60


class RateKey(NamedTuple):
    """A rate's source and year; the run fixes the target."""

    currency: CurrencyCode
    year: RateYear


class ValuationInput(NamedTuple):
    """What a valuation is computed from."""

    purchase_id: UUID
    amount: Decimal
    currency: CurrencyCode
    rate_year: RateYear

    @property
    def rate_key(self) -> RateKey:
        return RateKey(self.currency, self.rate_year)


def needs_rate(facts: ValuationInput, target: CurrencyCode) -> bool:
    """A purchase in another currency, not free."""
    return facts.currency != target and facts.amount != 0


def value(
    facts: ValuationInput,
    target: CurrencyCode,
    rate: Decimal | None,
    *,
    library: UserLibrary,
    version: ConversionVersion,
    calculated_at: datetime,
) -> PurchaseValuation:
    """One unsaved valuation, rounded half up once."""
    rate_needed = needs_rate(facts, target)
    if rate_needed != (rate is not None):
        raise ValueError(
            f"Purchase {facts.purchase_id} in {facts.currency} to {target} "
            f"takes {'a' if rate_needed else 'no'} rate, given {rate}."
        )
    if rate is None:
        amount = facts.amount
    elif rate <= 0:
        raise ValueError(f"Purchase {facts.purchase_id} given rate {rate}.")
    else:
        with localcontext(prec=PRODUCT_PRECISION):
            amount = facts.amount * rate
    return PurchaseValuation(
        library=library,
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


class Valuations(NamedTuple):
    """A run's rows, and inputs lacking a rate."""

    rows: list[PurchaseValuation]
    skipped: list[ValuationInput]


def value_all(
    snapshot: Iterable[ValuationInput],
    rates: Mapping[RateKey, Decimal],
    target: CurrencyCode,
    *,
    library: UserLibrary,
    version: ConversionVersion,
    calculated_at: datetime,
) -> Valuations:
    """Value each input; skip one without a rate."""
    rows: list[PurchaseValuation] = []
    skipped: list[ValuationInput] = []
    for facts in snapshot:
        rate: Decimal | None
        if not needs_rate(facts, target):
            rate = None
        elif facts.rate_key in rates:
            rate = rates[facts.rate_key]
        else:
            skipped.append(facts)
            continue
        rows.append(
            value(
                facts,
                target,
                rate,
                library=library,
                version=version,
                calculated_at=calculated_at,
            )
        )
    return Valuations(rows, skipped)


def publish_valuations(
    library: UserLibrary, valuations: Iterable[PurchaseValuation]
) -> None:
    """Replace the library's valuations whole.

    The caller holds the transaction and the conversion state's lock.
    """
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("Valuations publish inside a transaction.")
    rows = list(valuations)
    foreign = [row.purchase_id for row in rows if row.library_id != library.pk]
    if foreign:
        raise ValueError(f"Valuations of another library than {library.pk}: {foreign}")
    PurchaseValuation.objects.filter(library=library).delete()
    PurchaseValuation.objects.bulk_create(rows)
