import contextlib
import logging
from datetime import timedelta
from uuid import UUID

import requests
from django.db import transaction
from django.db.models import F, Q
from django.utils.timezone import now
from django_q.models import Schedule
from django_q.tasks import async_task, schedule

from games.models import ExchangeRate, Purchase, PurchaseConversionState, UserLibrary

logger = logging.getLogger("games")


def _get_exchange_rate(currency_from, currency_to, year):
    logger.debug(
        f"[convert_prices]: Looking for exchange rate in database: {currency_from}->{currency_to}"
    )
    rate = ExchangeRate.objects.filter(
        currency_from=currency_from, currency_to=currency_to, year=year
    ).first()
    if not rate:
        logger.debug(
            f"[convert_prices]: Getting exchange rate from {currency_from} to {currency_to} for {year}..."
        )
        try:
            response = requests.get(
                f"https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@{year}-01-01/v1/currencies/{currency_from.lower()}.json"
            )
            response.raise_for_status()
            data = response.json()
            currency_from_data = data.get(currency_from.lower())
            rate = currency_from_data.get(currency_to.lower())
            if rate:
                logger.info(f"[convert_prices]: Got {rate}, saving...")
                exchange_rate = ExchangeRate.objects.create(
                    currency_from=currency_from,
                    currency_to=currency_to,
                    year=year,
                    rate=rate,
                )
                rate = exchange_rate.rate
            else:
                logger.info("[convert_prices]: Could not get an exchange rate.")
        except requests.RequestException as e:
            logger.info(
                f"[convert_prices]: Failed to fetch exchange rate for {currency_from}->{currency_to} in {year}: {e}"
            )
    elif rate:
        rate = rate.rate
    return rate


RETRY_DELAY = timedelta(minutes=15)
MAX_ERROR_LENGTH = 240


class MissingExchangeRate(RuntimeError):
    pass


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
        if state is None or state.requested_version != requested_version:
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

    purchases = list(Purchase.objects.filter(library_id=library_pk).order_by("pk"))
    snapshot = [
        (
            purchase.pk,
            purchase.price,
            purchase.price_currency,
            purchase.date_purchased,
        )
        for purchase in purchases
    ]

    try:
        for purchase in purchases:
            source_currency = purchase.price_currency.upper()
            if source_currency == target_currency or purchase.price == 0:
                converted_price = purchase.price
            else:
                rate = _get_exchange_rate(
                    source_currency, target_currency, purchase.date_purchased.year
                )
                if rate is None:
                    raise MissingExchangeRate(
                        f"Exchange rate unavailable: {source_currency} to {target_currency}"
                    )
                converted_price = round(purchase.price * rate, 0)
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
            ):
                return
            current_snapshot = list(
                Purchase.objects.filter(library_id=library_pk)
                .order_by("pk")
                .values_list("pk", "price", "price_currency", "date_purchased")
            )
            if current_snapshot != snapshot:
                return
            Purchase.objects.bulk_update(
                purchases,
                ["converted_price", "converted_currency", "needs_price_update"],
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
    """Daily recovery for due failed conversions not superseded by a newer publish."""
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
