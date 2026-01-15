import logging

import requests
from django.template.defaultfilters import floatformat

logger = logging.getLogger("games")

from games.models import ExchangeRate, Purchase

# fixme: save preferred currency in user model
currency_to = "CZK"
currency_to = currency_to.upper()


def save_converted_info(purchase, converted_price, converted_currency):
    logger.info(
        f"Setting converted price of {purchase} to {converted_price} {converted_currency} (originally {purchase.price} {purchase.price_currency})"
    )
    purchase.converted_price = converted_price
    purchase.converted_currency = converted_currency
    purchase.save()


def convert_prices():
    purchases = Purchase.objects.filter(
        converted_price__isnull=True, converted_currency=""
    )
    if purchases.count() == 0:
        logger.info("[convert_prices]: No prices to convert.")

    for purchase in purchases:
        if purchase.price_currency.upper() == currency_to or purchase.price == 0:
            save_converted_info(purchase, purchase.price, currency_to)
            continue
        year = purchase.date_purchased.year
        currency_from = purchase.price_currency.upper()

        exchange_rate = ExchangeRate.objects.filter(
            currency_from=currency_from, currency_to=currency_to, year=year
        ).first()
        logger.info(
            f"[convert_prices]: Looking for exchange rate in database: {currency_from}->{currency_to}"
        )
        if not exchange_rate:
            logger.info(
                f"[convert_prices]: Getting exchange rate from {currency_from} to {currency_to} for {year}..."
            )
            try:
                # this API endpoint only accepts lowercase currency string
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
                else:
                    logger.info("[convert_prices]: Could not get an exchange rate.")
            except requests.RequestException as e:
                logger.info(
                    f"[convert_prices]: Failed to fetch exchange rate for {currency_from}->{currency_to} in {year}: {e}"
                )
        if exchange_rate:
            save_converted_info(
                purchase,
                floatformat(purchase.price * exchange_rate.rate, 0),
                currency_to,
            )
