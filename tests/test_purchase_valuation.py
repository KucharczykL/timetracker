"""A purchase's valuation: the rule, the reads and the publication."""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import cast
from unittest.mock import Mock

import pytest
from django.db import IntegrityError, transaction
from entries import record_entry
from purchases import record_purchase, remove_purchase, request_run

from games import tasks
from games.commands.calendar import SetCalendarDayZone
from games.events.dispatch import dispatch
from games.models import (
    ExchangeRate,
    Game,
    LegacyPurchase,
    Purchase,
    PurchaseConversionState,
    PurchaseValuation,
)
from games.projections import valuation_library_violations
from games.reads.purchases import (
    ValuedPurchase,
    stale_purchases,
    valuation_inputs,
    valued_purchases,
    with_valuation,
)
from games.valuations import ValuationInput, publish_valuations, value
from timetracker.temporal import TemporalValue

pytestmark = [pytest.mark.django_db, pytest.mark.untracked_games]

MARCH_2021 = TemporalValue.parse("2021-03-01")


@pytest.fixture(autouse=True)
def no_stored_rates():
    """The fixture rates seed every test database."""
    ExchangeRate.objects.all().delete()


@pytest.fixture
def entry(owned_library, stated_graph):
    graph = stated_graph(Game(name="Tunic", library=owned_library), owned_library)
    return record_entry(owned_library, graph.release)


@pytest.fixture
def rates(monkeypatch):
    """Rates the task reads, by pair and year."""
    table: dict[tuple[str, str, int], Decimal] = {}

    def read(source, target, year):
        return table.get((source, target, year))

    monkeypatch.setattr(tasks, "exchange_rate", read)
    return table


def _store_rate(source: str, target: str, year: int, rate: str) -> None:
    ExchangeRate.objects.update_or_create(
        currency_from=source,
        currency_to=target,
        year=year,
        defaults={"rate": Decimal(rate)},
    )


def _run(library, currency: str = "CZK") -> None:
    tasks.convert_library_prices(str(library.pk), request_run(library, currency))


def _year(purchase: Purchase) -> int:
    (facts,) = [
        facts
        for facts in valuation_inputs(purchase.library)
        if facts.purchase_id == purchase.pk
    ]
    return facts.rate_year


def _valuation(purchase: Purchase) -> PurchaseValuation:
    return PurchaseValuation.objects.get(purchase_id=purchase.pk)


def _current(purchase: Purchase) -> tuple[Decimal | None, str | None]:
    row = cast(
        ValuedPurchase,
        with_valuation(Purchase.objects.filter(pk=purchase.pk), purchase.library).get(),
    )
    if row.valuation_amount is None:
        return None, None
    return row.valuation_amount, row.valuation_currency


# The rate year


def test_the_year_is_the_purchased_day_s(entry):
    assert _year(record_purchase(entry, purchased=MARCH_2021)) == 2021


def test_an_open_start_takes_the_upper_year(entry):
    purchase = record_purchase(entry, purchased=TemporalValue.parse("../2015"))
    assert _year(purchase) == 2015


@pytest.mark.django_db(transaction=True)
def test_an_unknown_day_takes_the_recorded_year_in_the_calendar_zone(
    entry, owned_library
):
    dispatch(
        SetCalendarDayZone(day_zone="Pacific/Kiritimati"),
        actor=owned_library.user,
        library=owned_library,
        idempotency_key=str(uuid.uuid7()),
    )
    purchase = record_purchase(entry, purchased=None)
    Purchase.objects.filter(pk=purchase.pk).update(
        purchase_recorded_at=datetime(2025, 12, 31, 12, tzinfo=UTC)
    )

    assert _year(purchase) == 2026


def test_an_unknown_amount_and_a_removed_purchase_are_not_valued(entry):
    unknown = record_purchase(entry, amount=None)
    removed = remove_purchase(record_purchase(entry))

    keys = set(valued_purchases(entry.library).values_list("pk", flat=True))
    assert unknown.pk not in keys
    assert removed.pk not in keys


# The value


def test_another_currency_rounds_half_up_once(entry, rates):
    rates["EUR", "CZK", 2021] = Decimal("0.5")
    purchase = record_purchase(
        entry, amount=Decimal("10.05"), currency="EUR", purchased=MARCH_2021
    )

    _run(entry.library)

    valuation = _valuation(purchase)
    assert (valuation.amount, valuation.rate, valuation.rate_year) == (
        Decimal("5.03"),
        Decimal("0.5"),
        2021,
    )


def test_same_currency_and_free_take_no_rate(entry, monkeypatch):
    monkeypatch.setattr(
        tasks, "exchange_rate", Mock(side_effect=AssertionError("fetched a rate"))
    )
    same = record_purchase(entry, amount=Decimal("12.50"), currency="CZK")
    free = record_purchase(entry, amount=Decimal(0), currency="EUR")

    _run(entry.library)

    assert (_valuation(same).amount, _valuation(same).rate) == (Decimal("12.50"), None)
    assert (_valuation(free).amount, _valuation(free).rate) == (Decimal("0.00"), None)
    assert stale_purchases(entry.library).count() == 0


def test_an_unknown_amount_has_no_row(entry, rates):
    unknown = record_purchase(entry, amount=None)

    _run(entry.library)

    assert not PurchaseValuation.objects.filter(purchase_id=unknown.pk).exists()


# Current or stale


def _published(entry, *, currency="EUR", amount="10.00") -> Purchase:
    _store_rate("EUR", "CZK", 2021, "25")
    purchase = record_purchase(
        entry, amount=Decimal(amount), currency=currency, purchased=MARCH_2021
    )
    _run(entry.library)
    assert _current(purchase) == (Decimal("250.00"), "CZK")
    return purchase


def test_a_published_valuation_is_current(entry):
    purchase = _published(entry)

    assert list(stale_purchases(entry.library)) == []
    assert _valuation(purchase).version == 1


@pytest.mark.parametrize(
    "change",
    [
        {"amount": Decimal("11.00")},
        {"currency": "USD"},
        {"purchased": TemporalValue.parse("2022-01-01")},
    ],
    ids=["amount", "currency", "year"],
)
def test_a_changed_input_makes_it_stale(entry, change):
    purchase = _published(entry)
    Purchase.objects.filter(pk=purchase.pk).update(**change)

    assert list(stale_purchases(entry.library)) == [
        Purchase.objects.get(pk=purchase.pk)
    ]
    assert _current(purchase) == (None, None)


def test_a_corrected_rate_makes_it_stale(entry):
    purchase = _published(entry)
    _store_rate("EUR", "CZK", 2021, "26")

    assert [row.pk for row in stale_purchases(entry.library)] == [purchase.pk]


def test_a_stray_same_currency_rate_stales_nothing(entry):
    same = record_purchase(
        entry, amount=Decimal(5), currency="CZK", purchased=MARCH_2021
    )
    _run(entry.library)
    _store_rate("CZK", "CZK", 2021, "1.1")

    assert _current(same) == (Decimal("5.00"), "CZK")


def test_another_library_s_valuation_is_never_current(
    entry, django_user_model, stated_graph
):
    purchase = _published(entry)
    stranger = django_user_model.objects.create_user(username="stranger").library
    PurchaseValuation.objects.filter(purchase_id=purchase.pk).update(library=stranger)

    assert _current(purchase) == (None, None)


# Publication


def test_a_target_change_replaces_the_set_whole(entry):
    purchase = _published(entry)
    _store_rate("EUR", "USD", 2021, "1.1")

    _run(entry.library, "USD")

    assert list(
        PurchaseValuation.objects.filter(purchase_id=purchase.pk).values_list(
            "target_currency", "amount"
        )
    ) == [("USD", Decimal("11.00"))]


def test_a_missing_rate_keeps_the_old_set_and_the_legacy_cache(
    entry, rates, monkeypatch
):
    rates["EUR", "CZK", 2021] = Decimal(25)
    purchase = record_purchase(
        entry, amount=Decimal(10), currency="EUR", purchased=MARCH_2021
    )
    legacy = LegacyPurchase.objects.create(
        library=entry.library,
        price=10,
        price_currency="CZK",
        date_purchased=date(2021, 3, 1),
        converted_price=7,
        converted_currency="EUR",
    )
    _run(entry.library)
    published = PurchaseConversionState.objects.get(library=entry.library)
    LegacyPurchase.objects.filter(pk=legacy.pk).update(converted_price=7)
    record_purchase(entry, amount=Decimal(3), currency="GBP", purchased=MARCH_2021)
    monkeypatch.setattr(tasks, "schedule", Mock())

    _run(entry.library)

    state = PurchaseConversionState.objects.get(library=entry.library)
    legacy.refresh_from_db()
    assert state.status == PurchaseConversionState.Status.FAILED
    assert "GBP" in state.last_error
    assert list(PurchaseValuation.objects.values_list("purchase_id", "version")) == [
        (purchase.pk, published.published_version)
    ]
    assert legacy.converted_price == 7


def test_a_changed_purchase_publishes_nothing(entry, monkeypatch):
    purchase = record_purchase(entry, amount=Decimal(10), currency="CZK")

    def change_while_fetching(source, target, year):
        Purchase.objects.filter(pk=purchase.pk).update(amount=Decimal(11))
        return Decimal(1)

    record_purchase(entry, amount=Decimal(1), currency="EUR", purchased=MARCH_2021)
    monkeypatch.setattr(tasks, "exchange_rate", change_while_fetching)

    _run(entry.library)

    assert not PurchaseValuation.objects.exists()
    state = PurchaseConversionState.objects.get(library=entry.library)
    #: The next run supersedes it; the recovery re-enqueues it.
    assert (state.published_version, state.status) == (
        0,
        PurchaseConversionState.Status.RUNNING,
    )


def test_a_stale_worker_publishes_nothing(entry, rates):
    record_purchase(entry, amount=Decimal(10), currency="CZK")
    version = request_run(entry.library)
    request_run(entry.library)

    tasks.convert_library_prices(str(entry.library.pk), version)

    assert not PurchaseValuation.objects.exists()


def test_one_library_s_publication_leaves_another_s_rows(
    entry, django_user_model, stated_graph
):
    other_library = django_user_model.objects.create_user(username="other").library
    other_graph = stated_graph(
        Game(name="Celeste", library=other_library), other_library
    )
    other = record_purchase(
        record_entry(other_library, other_graph.release),
        amount=Decimal(4),
        currency="CZK",
    )
    _run(other_library)

    _published(entry)

    assert _valuation(other).library_id == other_library.pk


def test_a_free_purchase_beside_a_paid_one_in_its_currency_and_year(entry, rates):
    rates["EUR", "CZK", 2021] = Decimal(25)
    free = record_purchase(
        entry, amount=Decimal(0), currency="EUR", purchased=MARCH_2021
    )
    paid = record_purchase(
        entry, amount=Decimal(2), currency="EUR", purchased=MARCH_2021
    )

    _run(entry.library)

    assert (_valuation(free).amount, _valuation(free).rate) == (Decimal("0.00"), None)
    assert (_valuation(paid).amount, _valuation(paid).rate) == (
        Decimal("50.00"),
        Decimal(25),
    )


def test_one_fetch_per_currency_and_year(entry, monkeypatch):
    fetch = Mock(return_value=Decimal(25))
    monkeypatch.setattr(tasks, "exchange_rate", fetch)
    record_purchase(entry, amount=Decimal(0), currency="EUR", purchased=MARCH_2021)
    record_purchase(entry, amount=Decimal(1), currency="EUR", purchased=MARCH_2021)
    record_purchase(entry, amount=Decimal(2), currency="EUR", purchased=MARCH_2021)

    _run(entry.library)

    fetch.assert_called_once_with("EUR", "CZK", 2021)
    assert (
        len(set(PurchaseValuation.objects.values_list("calculated_at", flat=True))) == 1
    )


def test_a_removed_rate_makes_it_stale(entry):
    purchase = _published(entry)
    ExchangeRate.objects.filter(currency_from="EUR").delete()

    assert [row.pk for row in stale_purchases(entry.library)] == [purchase.pk]


def test_a_pending_target_keeps_the_published_valuation_current(entry):
    purchase = _published(entry)

    request_run(entry.library, "USD")

    assert _current(purchase) == (Decimal("250.00"), "CZK")


def test_a_failed_valuation_write_rolls_back_the_legacy_cache(entry, monkeypatch):
    purchase = _published(entry)
    legacy = LegacyPurchase.objects.create(
        library=entry.library,
        price=10,
        price_currency="CZK",
        date_purchased=date(2021, 3, 1),
    )
    LegacyPurchase.objects.filter(pk=legacy.pk).update(converted_price=7)
    monkeypatch.setattr(tasks, "schedule", Mock())

    def fail(*args, **kwargs):
        raise RuntimeError("valuation write interrupted")

    monkeypatch.setattr(PurchaseValuation.objects, "bulk_create", fail)

    _run(entry.library)

    legacy.refresh_from_db()
    state = PurchaseConversionState.objects.get(library=entry.library)
    assert legacy.converted_price == 7
    assert _valuation(purchase).version == 1
    assert state.status == PurchaseConversionState.Status.FAILED


# The writer's refusals


def _facts(currency: str = "EUR", amount: str = "10") -> ValuationInput:
    return ValuationInput(
        purchase_id=uuid.uuid7(),
        amount=Decimal(amount),
        currency=currency,
        rate_year=2021,
    )


@pytest.mark.parametrize(
    ("facts", "rate"),
    [
        (_facts("CZK"), Decimal(1)),
        (_facts("EUR", "0"), Decimal(25)),
        (_facts("EUR"), None),
        (_facts("EUR"), Decimal(0)),
    ],
    ids=["same currency with a rate", "free with a rate", "no rate", "zero rate"],
)
def test_value_refuses_a_rate_that_breaks_the_rule(owned_library, facts, rate):
    with pytest.raises(ValueError):
        value(
            facts,
            "CZK",
            rate,
            library=owned_library,
            version=1,
            calculated_at=datetime.now(UTC),
        )


def test_publication_refuses_another_library_s_row(owned_library, django_user_model):
    stranger = django_user_model.objects.create_user(username="stranger").library
    row = value(
        _facts("CZK"),
        "CZK",
        None,
        library=stranger,
        version=1,
        calculated_at=datetime.now(UTC),
    )

    with pytest.raises(ValueError):
        publish_valuations(owned_library, [row])


def test_the_table_refuses_a_missing_rate(owned_library):
    row = value(
        _facts("CZK"),
        "CZK",
        None,
        library=owned_library,
        version=1,
        calculated_at=datetime.now(UTC),
    )
    row.source_currency = "EUR"

    with pytest.raises(IntegrityError), transaction.atomic():
        row.save()


def test_the_audit_reports_another_library_s_purchase(entry, django_user_model):
    purchase = _published(entry)
    stranger = django_user_model.objects.create_user(username="stranger").library
    PurchaseValuation.objects.update(library=stranger)
    (row,) = PurchaseValuation.objects.all()

    sentence = (
        f"PurchaseValuation.purchase_id: {row.pk} of library {stranger.pk} "
        f"names another library's Purchase {purchase.pk}"
    )
    assert valuation_library_violations([stranger.pk]) == [sentence]
    assert valuation_library_violations([entry.library.pk]) == []
