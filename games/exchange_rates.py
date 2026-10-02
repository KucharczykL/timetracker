"""One exchange rate per pair and year."""

import logging
from decimal import Decimal

import requests

from games.models import RATE_PLACES, ExchangeRate
from games.valuations import CurrencyCode, RateYear

logger = logging.getLogger("games")

QUANTUM = Decimal(1).scaleb(-RATE_PLACES)
#: The column holds twelve integer digits.
CEILING = Decimal(10) ** 12
#: The API speaks lowercase codes.
RATE_SOURCE = "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@{year}-01-01/v1/currencies/{currency}.json"
#: The source holds no such table.
ABSENT_STATUS = 404


class RateFetchFailed(RuntimeError):
    """The source did not answer; retry later."""


def exchange_rate(
    source: CurrencyCode, target: CurrencyCode, year: RateYear
) -> Decimal | None:
    """The stored rate, else fetched; None when the source has none.

    A source that does not answer raises `RateFetchFailed`.
    """
    stored = ExchangeRate.objects.filter(
        currency_from=source, currency_to=target, year=year
    ).first()
    if stored is not None:
        return stored.rate
    url = RATE_SOURCE.format(year=year, currency=source.lower())
    logger.debug(
        "[exchange_rate]: fetching %s->%s %s from %s", source, target, year, url
    )
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        data = response.json(parse_float=Decimal)
    except requests.RequestException as error:
        logger.warning(
            "[exchange_rate]: fetch of %s->%s %s from %s failed: %s",
            source,
            target,
            year,
            url,
            error,
        )
        if (
            isinstance(error, requests.HTTPError)
            and error.response is not None
            and error.response.status_code == ABSENT_STATUS
        ):
            return None
        raise RateFetchFailed(
            f"Fetching {source}->{target} for {year} failed: {error}"
        ) from error
    rates = data.get(source.lower()) if isinstance(data, dict) else None
    if not isinstance(rates, dict):
        logger.warning(
            "[exchange_rate]: %s answered no %s table for %s", url, source, year
        )
        return None
    answered = rates.get(target.lower())
    rate = _usable_rate(answered)
    if rate is None:
        logger.warning(
            "[exchange_rate]: %s answered no usable %s->%s rate for %s: %r",
            url,
            source,
            target,
            year,
            answered,
        )
        return None
    logger.info("[exchange_rate]: storing %s->%s %s = %s", source, target, year, rate)
    stored, _ = ExchangeRate.objects.get_or_create(
        currency_from=source,
        currency_to=target,
        year=year,
        defaults={"rate": rate},
    )
    return stored.rate


def _is_storable(rate: Decimal) -> bool:
    return 0 < rate < CEILING


def _usable_rate(answered: object) -> Decimal | None:
    """The quantized rate, if positive and storable."""
    if isinstance(answered, bool) or not isinstance(answered, Decimal | int):
        return None
    # Quantizing a too-wide number raises.
    if not _is_storable(Decimal(answered)):
        return None
    rate = Decimal(answered).quantize(QUANTUM)
    return rate if _is_storable(rate) else None
