"""The Purchases list's Name and Amount cells."""

from decimal import Decimal

import pytest
from entries import record_entry
from purchases import record_purchase, request_run

from common.components import PurchaseAmount, PurchaseName
from games import tasks
from games.models import ExchangeRate, Game, Purchase
from timetracker.temporal import TemporalValue

pytestmark = [pytest.mark.django_db, pytest.mark.untracked_games]


@pytest.fixture
def entry(owned_library, stated_graph):
    graph = stated_graph(Game(name="Tunic", library=owned_library), owned_library)
    return record_entry(owned_library, graph.release)


def _listed(purchase) -> Purchase:
    return Purchase.objects.annotated_for_filtering(purchase.library).get(
        pk=purchase.pk
    )


def test_a_game_purchase_names_the_game(entry):
    assert ">Tunic<" in str(PurchaseName(record_purchase(entry)))


def test_a_named_product_leads(entry):
    purchase = record_purchase(entry, kind="season_pass", name="Pass")

    assert "Pass · Tunic" in str(PurchaseName(purchase))


@pytest.mark.parametrize(("amount", "words"), [(None, "Unknown"), (Decimal(0), "Free")])
def test_an_unknown_or_free_amount_says_so(entry, amount, words):
    assert words in str(PurchaseAmount(_listed(record_purchase(entry, amount=amount))))


def test_a_valuation_in_the_same_currency_is_not_repeated(entry, owned_library):
    purchase = record_purchase(entry, amount=Decimal("12.50"), currency="EUR")
    tasks.convert_library_prices(
        str(owned_library.pk), request_run(owned_library, "EUR")
    )

    cell = str(PurchaseAmount(_listed(purchase)))

    assert "12.50 EUR" in cell
    assert cell.count("EUR") == 1


def test_a_foreign_valuation_stands_beside(entry, owned_library):
    ExchangeRate.objects.update_or_create(
        currency_from="USD",
        currency_to="EUR",
        year=2021,
        defaults={"rate": Decimal("0.5")},
    )
    purchase = record_purchase(
        entry,
        amount=Decimal(10),
        currency="USD",
        purchased=TemporalValue.parse("2021-03-01"),
    )
    tasks.convert_library_prices(
        str(owned_library.pk), request_run(owned_library, "EUR")
    )

    cell = str(PurchaseAmount(_listed(purchase)))

    assert "10.00 USD" in cell
    assert "(5.00 EUR)" in cell
