import contextlib
import logging
from datetime import timedelta
from decimal import Decimal
from uuid import UUID

from django.db import transaction
from django.db.models import F, Q
from django.utils.timezone import now
from django_q.models import Schedule
from django_q.tasks import async_task, schedule

from games.conversion import request_revaluation
from games.exchange_rates import exchange_rate
from games.models import (
    LegacyPurchase,
    PurchaseConversionState,
    UserLibrary,
)
from games.reads.purchases import stale_purchases, valuation_inputs
from games.valuations import (
    ValuationInput,
    needs_rate,
    publish_valuations,
    value,
)

logger = logging.getLogger("games")


RETRY_DELAY = timedelta(minutes=15)
MAX_ERROR_LENGTH = 240


class MissingExchangeRate(RuntimeError):
    pass


def _required_rate(source: str, target: str, year: int) -> Decimal:
    rate = exchange_rate(source, target, year)
    if rate is None:
        raise MissingExchangeRate(f"Exchange rate unavailable: {source} to {target}")
    return rate


type RateKey = tuple[str, int]  # source currency, year


def _rates_for(snapshot: list[ValuationInput], target: str) -> dict[RateKey, Decimal]:
    rates: dict[RateKey, Decimal] = {}
    for facts in snapshot:
        key = (facts.currency, facts.rate_year)
        if needs_rate(facts, target) and key not in rates:
            rates[key] = _required_rate(facts.currency, target, facts.rate_year)
    return rates


def _concise_error(error: Exception) -> str:
    return " ".join(str(error).split())[:MAX_ERROR_LENGTH]


def _mark_failed(
    library_id: str,
    requested_version: int,
    error: Exception,
    *,
    schedule_retry: bool,
) -> None:
    retry_at = now() + RETRY_DELAY
    library_pk = UUID(library_id)
    should_schedule = False
    with transaction.atomic():
        state = (
            PurchaseConversionState.objects.select_for_update()
            .filter(library_id=library_pk)
            .first()
        )
        if (
            state is None
            or state.requested_version != requested_version
            or state.published_version >= requested_version
        ):
            return
        should_schedule = schedule_retry and state.retry_at is None
        state.status = PurchaseConversionState.Status.FAILED
        state.retry_at = retry_at
        state.last_error = _concise_error(error)
        state.save(update_fields=["status", "retry_at", "last_error"])

    if should_schedule:
        schedule(
            "games.tasks.convert_library_prices",
            library_id,
            requested_version,
            schedule_type=Schedule.ONCE,
            next_run=retry_at,
            name=f"Retry price conversion {library_id} v{requested_version}",
        )


def convert_library_prices(library_id: str, requested_version: int) -> None:
    """Convert one immutable snapshot and publish it atomically if still current."""
    library_pk = UUID(library_id)
    with transaction.atomic():
        state = (
            PurchaseConversionState.objects.select_for_update()
            .filter(library_id=library_pk)
            .first()
        )
        if (
            state is None
            or state.requested_version != requested_version
            or state.published_version >= requested_version
        ):
            return
        target_currency = state.requested_currency.upper()
        schedule_retry = state.retry_at is None
        state.status = PurchaseConversionState.Status.RUNNING
        state.last_error = ""
        state.save(update_fields=["status", "last_error"])

    purchases = list(
        LegacyPurchase.objects.filter(library_id=library_pk).order_by("pk")
    )
    snapshot = [
        (
            purchase.pk,
            purchase.price,
            purchase.price_currency,
            purchase.date_purchased,
        )
        for purchase in purchases
    ]

    library = UserLibrary.objects.get(pk=library_pk)
    try:
        valuation_snapshot = valuation_inputs(library)
        rates = _rates_for(valuation_snapshot, target_currency)
        for purchase in purchases:
            source_currency = purchase.price_currency.upper()
            if source_currency == target_currency or purchase.price == 0:
                converted_price = purchase.price
            else:
                rate = _required_rate(
                    source_currency, target_currency, purchase.date_purchased.year
                )
                converted_price = round(purchase.price * float(rate), 0)
            purchase.converted_price = converted_price
            purchase.converted_currency = target_currency
            purchase.needs_price_update = False

        with transaction.atomic():
            state = PurchaseConversionState.objects.select_for_update().get(
                library_id=library_pk
            )
            if (
                state.requested_version != requested_version
                or state.requested_currency.upper() != target_currency
                or state.published_version >= requested_version
            ):
                return
            current_snapshot = list(
                LegacyPurchase.objects.filter(library_id=library_pk)
                .order_by("pk")
                .values_list("pk", "price", "price_currency", "date_purchased")
            )
            if (
                current_snapshot != snapshot
                or valuation_inputs(library) != valuation_snapshot
            ):
                return
            LegacyPurchase.objects.bulk_update(
                purchases,
                ["converted_price", "converted_currency", "needs_price_update"],
            )
            calculated_at = now()
            publish_valuations(
                library,
                (
                    value(
                        facts,
                        target_currency,
                        rates.get((facts.currency, facts.rate_year)),
                        version=requested_version,
                        calculated_at=calculated_at,
                    )
                    for facts in valuation_snapshot
                ),
            )
            state.published_version = requested_version
            state.published_currency = target_currency
            state.status = PurchaseConversionState.Status.COMPLETE
            state.retry_at = None
            state.last_error = ""
            state.save(
                update_fields=[
                    "published_version",
                    "published_currency",
                    "status",
                    "retry_at",
                    "last_error",
                ]
            )
    except Exception as error:
        logger.exception(
            "[convert_library_prices]: conversion failed for library %s version %s",
            library_id,
            requested_version,
        )
        _mark_failed(
            library_id,
            requested_version,
            error,
            schedule_retry=schedule_retry,
        )


def recover_library_price_conversions() -> None:
    """Daily recovery: due failed runs, then stale valuations at rest."""
    stale = PurchaseConversionState.objects.filter(
        requested_version__gt=F("published_version")
    ).filter(
        Q(
            status__in=(
                PurchaseConversionState.Status.PENDING,
                PurchaseConversionState.Status.RUNNING,
            )
        )
        | Q(status=PurchaseConversionState.Status.FAILED, retry_at__lte=now())
    )
    for state in stale:
        async_task(
            "games.tasks.convert_library_prices",
            str(state.library_id),
            state.requested_version,
        )
    at_rest = PurchaseConversionState.objects.filter(
        requested_version=F("published_version")
    ).select_related("library")
    for state in at_rest:
        if stale_purchases(state.library).exists():
            request_revaluation(state.library)


def convert_prices() -> None:
    """Compatibility entry point: request current targets for every library."""
    from games.conversion import request_conversion
    from timetracker.settings_resolver import resolve_for_user_with_origin

    for library in UserLibrary.objects.select_related("user"):
        target = resolve_for_user_with_origin(
            library.user, "DEFAULT_DISPLAY_CURRENCY"
        ).value
        request_conversion(library, str(target))


def calculate_price_per_game():
    """
    This task is deprecated because price_per_game is now a GeneratedField.
    It is kept here to prevent errors from lingering scheduled tasks.
    """
    # Best-effort by design: whatever state the scheduler tables are in,
    # a lingering schedule for the retired task must never break anything.
    with contextlib.suppress(Exception):
        from django_q.models import Schedule

        Schedule.objects.filter(func="games.tasks.calculate_price_per_game").delete()
