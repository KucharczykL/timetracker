"""One exchange rate per pair and year."""

import logging
from decimal import Decimal

import requests

from games.models import RATE_PLACES, ExchangeRate

logger = logging.getLogger("games")

QUANTUM = Decimal(1).scaleb(-RATE_PLACES)
RATE_SOURCE = "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@{year}-01-01/v1/currencies/{currency}.json"


def exchange_rate(source: str, target: str, year: int) -> Decimal | None:
    """The stored rate, else fetched and stored."""
    stored = ExchangeRate.objects.filter(
        currency_from=source, currency_to=target, year=year
    ).first()
    if stored is not None:
        return stored.rate
    logger.debug(
        "[convert_prices]: Getting exchange rate from %s to %s for %s...",
        source,
        target,
        year,
    )
    try:
        response = requests.get(
            RATE_SOURCE.format(year=year, currency=source.lower()), timeout=30
        )
        response.raise_for_status()
        data = response.json(parse_float=Decimal)
    except requests.RequestException as error:
        logger.info(
            "[convert_prices]: Failed to fetch exchange rate for %s->%s in %s: %s",
            source,
            target,
            year,
            error,
        )
        return None
    rate = (data.get(source.lower()) or {}).get(target.lower())
    if not rate:
        logger.info("[convert_prices]: Could not get an exchange rate.")
        return None
    logger.info("[convert_prices]: Got %s, saving...", rate)
    return ExchangeRate.objects.create(
        currency_from=source,
        currency_to=target,
        year=year,
        rate=Decimal(rate).quantize(QUANTUM),
    ).rate
