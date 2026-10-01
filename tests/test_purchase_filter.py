"""The Purchase filter and its valuation alias."""

from decimal import Decimal

import pytest
from entries import record_entry
from purchases import record_purchase, request_run

from common.criteria import FilterQueryContext
from games import tasks
from games.filters import (
    filter_query_context_for_library,
    filter_queryset_for_library,
)
from games.models import ExchangeRate, Game, Purchase
from games.reads.purchases import UnscopedValuationRead
from timetracker.temporal import TemporalValue

pytestmark = [pytest.mark.django_db, pytest.mark.untracked_games]

MARCH_2021 = TemporalValue.parse("2021-03-01")


@pytest.fixture(autouse=True)
def no_stored_rates():
    ExchangeRate.objects.all().delete()


@pytest.fixture
def entry(owned_library, stated_graph):
    graph = stated_graph(Game(name="Tunic", library=owned_library), owned_library)
    return record_entry(owned_library, graph.release)


def _value(library, currency: str = "EUR") -> None:
    tasks.convert_library_prices(str(library.pk), request_run(library, currency))


# The valuation alias


def test_a_second_call_with_the_same_library_is_a_no_op(entry, owned_library):
    rows = Purchase.objects.annotated_for_filtering(owned_library)

    assert rows.annotated_for_filtering(owned_library).query.annotations.keys() == (
        rows.query.annotations.keys()
    )
    assert rows.annotated_for_filtering() is not None


def test_a_call_naming_another_library_is_refused(owned_library, django_user_model):
    stranger = django_user_model.objects.create_user(username="stranger").library
    rows = Purchase.objects.annotated_for_filtering(owned_library)

    with pytest.raises(ValueError, match="valuation alias"):
        rows.annotated_for_filtering(stranger)


def test_an_unscoped_alias_resolves_and_refuses_to_execute():
    rows = Purchase.objects.none().annotated_for_filtering()
    narrowed = Purchase.objects.annotated_for_filtering().filter(valuation_amount__gt=1)

    assert list(rows.filter(valuation_amount__gt=1)) == []
    with pytest.raises(UnscopedValuationRead):
        list(narrowed)


def test_an_unscoped_queryset_naming_no_alias_executes(entry):
    record_purchase(entry, purchased=MARCH_2021)

    assert Purchase.objects.annotated_for_filtering().count() == 1


def test_the_scoped_alias_reads_the_current_valuation(entry, owned_library):
    purchase = record_purchase(
        entry, amount=Decimal("12.50"), currency="EUR", purchased=MARCH_2021
    )
    unvalued = record_purchase(entry, amount=None, purchased=MARCH_2021)
    _value(owned_library)

    rows = {
        row.pk: (row.valuation_amount, row.valuation_currency)
        for row in Purchase.objects.annotated_for_filtering(owned_library)
    }

    assert rows[purchase.pk] == (Decimal("12.50"), "EUR")
    assert rows[unvalued.pk] == (None, "EUR")


def test_the_validation_context_accepts_a_valuation_filter():
    rows = FilterQueryContext.for_validation().queryset_for(Purchase)

    assert list(rows.filter(valuation_amount__gt=1)) == []


def test_both_library_scopes_carry_the_alias(entry, owned_library):
    purchase = record_purchase(entry, amount=Decimal(5), purchased=MARCH_2021)
    _value(owned_library)
    context = filter_query_context_for_library(owned_library)

    for rows in (
        context.queryset_for(Purchase),
        filter_queryset_for_library("purchase", owned_library),
    ):
        assert list(rows.filter(valuation_amount=5).values_list("pk", flat=True)) == [
            purchase.pk
        ]
