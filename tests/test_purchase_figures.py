"""The statistics' purchase figures."""

from decimal import Decimal

import pytest
from entries import record_entry
from graphs import default_graph
from purchases import record_purchase, refund_purchase, request_run

from games import tasks
from games.models import ExchangeRate, Game
from games.reads.purchase_figures import (
    purchase_figures,
    purchases_matching,
    unpriced_in_scope,
    unvalued_in_scope,
)
from timetracker.temporal import TemporalValue

pytestmark = [pytest.mark.django_db, pytest.mark.untracked_games]

IN_2021 = TemporalValue.parse("2021-03-01")


@pytest.fixture(autouse=True)
def no_rates(monkeypatch):
    """Only same-currency purchases value."""
    ExchangeRate.objects.all().delete()
    monkeypatch.setattr(tasks, "exchange_rate", lambda *_: None)


@pytest.fixture
def entry(owned_library):
    graph = default_graph(Game(name="Tunic", library=owned_library), owned_library)
    return record_entry(owned_library, graph.release)


def _value(library) -> None:
    tasks.convert_library_prices(str(library.pk), request_run(library, "EUR"))


def test_a_day_across_new_year_counts_all_time_only(entry, owned_library):
    record_purchase(entry, purchased=TemporalValue.parse("2021-12/2022-01"))

    assert purchase_figures(owned_library, 2021).purchases == 0
    assert purchase_figures(owned_library, 2022).purchases == 0
    assert purchase_figures(owned_library, None).purchases == 1


@pytest.mark.parametrize("year", [2021, None])
def test_refunded_counts_the_refund_act(entry, owned_library, year):
    refund_purchase(
        record_purchase(entry, kind="season_pass", name="P", purchased=IN_2021),
        TemporalValue.parse("2021-04-01"),
    )
    record_purchase(entry, purchased=IN_2021)

    figures = purchase_figures(owned_library, year)

    assert (figures.purchases, figures.refunded) == (2, 1)


@pytest.mark.parametrize("year", [2021, None])
def test_total_spent_sums_unrefunded_valuations(entry, owned_library, year):
    record_purchase(entry, amount=Decimal("20.00"), purchased=IN_2021)
    record_purchase(entry, amount=Decimal("5.50"), purchased=IN_2021)
    refund_purchase(
        record_purchase(entry, kind="upgrade", amount=Decimal(100), purchased=IN_2021),
        TemporalValue.parse("2021-04-01"),
    )
    _value(owned_library)

    figures = purchase_figures(owned_library, year)

    assert figures.total_spent == Decimal("25.50")
    assert figures.valued == 2


@pytest.mark.parametrize("year", [2021, None])
def test_unpriced_and_unvalued_are_counted_apart(entry, owned_library, year):
    record_purchase(entry, amount=None, purchased=IN_2021)
    record_purchase(entry, amount=Decimal(9), currency="USD", purchased=IN_2021)
    record_purchase(entry, amount=Decimal(0), purchased=IN_2021)
    _value(owned_library)

    figures = purchase_figures(owned_library, year)

    assert (figures.unpriced, figures.unvalued, figures.valued) == (1, 1, 1)
    assert purchases_matching(owned_library, unpriced_in_scope(year)).count() == 1
    assert purchases_matching(owned_library, unvalued_in_scope(year)).count() == 1


def test_a_free_purchase_is_valued_and_adds_nothing(entry, owned_library):
    record_purchase(entry, amount=Decimal(0), purchased=IN_2021)
    record_purchase(entry, amount=Decimal(10), purchased=IN_2021)
    _value(owned_library)

    figures = purchase_figures(owned_library, None)

    assert (figures.total_spent, figures.valued) == (Decimal(10), 2)
