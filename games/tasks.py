import logging

import requests
from django.db import models
from django.template.defaultfilters import floatformat

logger = logging.getLogger("games")

from games.models import ExchangeRate, Purchase

# fixme: save preferred currency in user model
currency_to = "CZK"
currency_to = currency_to.upper()


def _get_exchange_rate(currency_from, currency_to, year):
    logger.info(
        f"[convert_prices]: Looking for exchange rate in database: {currency_from}->{currency_to}"
    )
    exchange_rate = ExchangeRate.objects.filter(
        currency_from=currency_from, currency_to=currency_to, year=year
    ).first()
    if not exchange_rate:
        logger.info(
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
                    rate=floatformat(rate, 2),
                )
                exchange_rate = exchange_rate.rate
            else:
                logger.info("[convert_prices]: Could not get an exchange rate.")
        except requests.RequestException as e:
            logger.info(
                f"[convert_prices]: Failed to fetch exchange rate for {currency_from}->{currency_to} in {year}: {e}"
            )
    elif exchange_rate:
        exchange_rate = exchange_rate.rate
    return exchange_rate


def _save_converted_price(purchase, converted_price, needs_update):
    logger.info(
        f"Setting converted price of {purchase} to {converted_price} {currency_to} (originally {purchase.price} {purchase.price_currency})"
    )
    purchase.converted_price = converted_price
    purchase.converted_currency = currency_to
    if needs_update:
        purchase.needs_price_update = False
    purchase.save(update_fields=["converted_price", "converted_currency", "needs_price_update"])


def convert_prices():
    purchases = Purchase.objects.filter(
        models.Q(needs_price_update=True) | models.Q(converted_price__isnull=True)
    ).distinct()
    if purchases.count() == 0:
        logger.info("[convert_prices]: No prices to convert.")
        return

    for purchase in purchases:
        needs_update = purchase.needs_price_update
        if purchase.price_currency.upper() == currency_to or purchase.price == 0:
            _save_converted_price(purchase, purchase.price, needs_update)
            continue
        year = purchase.date_purchased.year
        currency_from = purchase.price_currency.upper()
        exchange_rate = _get_exchange_rate(currency_from, currency_to, year)
        if exchange_rate:
            _save_converted_price(
                purchase,
                floatformat(purchase.price * exchange_rate, 0),
                needs_update,
            )


def calculate_price_per_game():
    """
    This task is deprecated because price_per_game is now a GeneratedField.
    It is kept here to prevent errors from lingering scheduled tasks.
    """
    try:
        from django_q.models import Schedule

        Schedule.objects.filter(func="games.tasks.calculate_price_per_game").delete()
    except Exception:
        pass
