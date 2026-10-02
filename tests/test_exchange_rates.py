"""A rate is a decimal, fetched without a float."""

import json
from decimal import Decimal
from importlib import import_module
from unittest.mock import Mock

import pytest
import requests
from django.db import IntegrityError, transaction

from games import exchange_rates
from games.models import ExchangeRate

RATE_MIGRATION = import_module("games.migrations.0029_exchangerate_decimal_rate")


@pytest.fixture(autouse=True)
def no_stored_rates(request):
    """The fixture rates seed every test database."""
    if "django_db" in request.keywords:
        ExchangeRate.objects.all().delete()


def _answer(text: str) -> Mock:
    response = Mock()
    response.raise_for_status = Mock()
    response.json = Mock(side_effect=lambda **kwargs: json.loads(text, **kwargs))
    return response


def test_the_copy_keeps_the_shortest_spelling():
    #: The binary expansion rounds up; repr does not.
    assert RATE_MIGRATION.decimal_rate(23.1234567890125) == Decimal("23.123456789012")
    assert RATE_MIGRATION.decimal_rate(0.1) == Decimal("0.100000000000")
    assert RATE_MIGRATION.decimal_rate(25.123456789012345) == Decimal("25.123456789012")


@pytest.mark.django_db
def test_a_fetched_rate_is_stored_quantized_and_answered(monkeypatch):
    answer = _answer('{"usd": {"czk": 23.123456789012345678}}')
    get = Mock(return_value=answer)
    monkeypatch.setattr(exchange_rates.requests, "get", get)

    rate = exchange_rates.exchange_rate("USD", "CZK", 2025)

    get.assert_called_once_with(
        "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@2025-01-01"
        "/v1/currencies/usd.json",
        timeout=30,
    )
    stored = ExchangeRate.objects.get(currency_from="USD", currency_to="CZK", year=2025)
    assert rate == stored.rate == Decimal("23.123456789012")
    assert isinstance(rate, Decimal)


@pytest.mark.django_db
def test_a_stored_rate_is_read_without_a_fetch(monkeypatch):
    ExchangeRate.objects.create(
        currency_from="USD", currency_to="CZK", year=2025, rate=Decimal("22.5")
    )
    monkeypatch.setattr(
        exchange_rates.requests, "get", Mock(side_effect=AssertionError("fetched"))
    )

    assert exchange_rates.exchange_rate("USD", "CZK", 2025) == Decimal("22.5")


@pytest.mark.django_db
def test_a_currency_the_answer_lacks_is_none(monkeypatch):
    monkeypatch.setattr(
        exchange_rates.requests,
        "get",
        Mock(return_value=_answer('{"usd": {"eur": 0.9}}')),
    )

    assert exchange_rates.exchange_rate("USD", "CZK", 2025) is None
    assert not ExchangeRate.objects.exists()


@pytest.mark.django_db
def test_a_failed_request_raises_for_a_retry(monkeypatch):
    monkeypatch.setattr(
        exchange_rates.requests,
        "get",
        Mock(side_effect=requests.ConnectionError("offline")),
    )

    with pytest.raises(exchange_rates.RateFetchFailed, match="offline"):
        exchange_rates.exchange_rate("USD", "CZK", 2023)
    assert not ExchangeRate.objects.exists()


@pytest.mark.django_db
def test_an_absent_year_is_none(monkeypatch):
    response = requests.Response()
    response.status_code = 404
    monkeypatch.setattr(
        exchange_rates.requests,
        "get",
        Mock(side_effect=requests.HTTPError("not found", response=response)),
    )

    assert exchange_rates.exchange_rate("USD", "CZK", 1990) is None


@pytest.mark.django_db
@pytest.mark.parametrize(
    "text",
    [
        "[]",
        '{"eur": {}}',
        '{"usd": {"czk": 0.0000000000001}}',
        '{"usd": {"czk": 0}}',
        '{"usd": {"czk": -2}}',
        '{"usd": {"czk": true}}',
        '{"usd": {"czk": "n/a"}}',
        '{"usd": {"czk": [1]}}',
        '{"usd": {"czk": 1e30}}',
    ],
    ids=[
        "not an object",
        "no source table",
        "rounds to zero",
        "zero",
        "negative",
        "boolean",
        "text",
        "list",
        "too wide",
    ],
)
def test_an_unusable_answer_is_none_and_stores_nothing(monkeypatch, text):
    monkeypatch.setattr(
        exchange_rates.requests, "get", Mock(return_value=_answer(text))
    )

    assert exchange_rates.exchange_rate("USD", "CZK", 2025) is None
    assert not ExchangeRate.objects.exists()


@pytest.mark.django_db
def test_a_rate_stored_during_the_fetch_wins(monkeypatch):
    def store_then_answer(*args, **kwargs):
        ExchangeRate.objects.create(
            currency_from="USD", currency_to="CZK", year=2025, rate=Decimal(22)
        )
        return _answer('{"usd": {"czk": 23}}')

    monkeypatch.setattr(exchange_rates.requests, "get", store_then_answer)

    assert exchange_rates.exchange_rate("USD", "CZK", 2025) == Decimal(22)


@pytest.mark.django_db
def test_the_table_refuses_a_rate_that_is_not_positive():
    with pytest.raises(IntegrityError), transaction.atomic():
        ExchangeRate.objects.create(
            currency_from="USD", currency_to="CZK", year=2025, rate=Decimal(0)
        )
