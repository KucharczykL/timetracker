"""The squash refuses data the elided passes needed."""

from importlib import import_module

import pytest
from django.db import connection
from entries import record_entry
from purchases import record_purchase

from games.models import ExchangeRate, Game

SQUASH = import_module(
    "games.migrations."
    "0019_device_access_end_squashed_0036_defer_library_event_stream_matches_library"
)
CONVERSION = import_module("games.migrations.0031_purchase_conversion")

pytestmark = pytest.mark.django_db


class _SchemaEditor:
    connection = connection


def _guard() -> None:
    SQUASH.refuse_unconverted_data(None, _SchemaEditor())


@pytest.fixture(autouse=True)
def no_stored_rates():
    ExchangeRate.objects.all().delete()


def test_the_guard_is_the_first_operation():
    first = SQUASH.Migration.operations[0]
    assert first.code is SQUASH.refuse_unconverted_data
    assert first.elidable


def test_empty_tables_pass():
    _guard()


def test_a_stored_rate_is_refused():
    ExchangeRate.objects.create(
        currency_from="CZK", currency_to="EUR", year=2020, rate="0.04"
    )
    with pytest.raises(RuntimeError, match="drop and rebuild"):
        _guard()


def test_a_purchase_row_is_refused(owned_library, stated_graph):
    graph = stated_graph(Game(name="Tunic", library=owned_library), owned_library)
    record_purchase(record_entry(owned_library, graph.release))
    with pytest.raises(RuntimeError, match="image before the squash"):
        _guard()


def test_the_conversion_refuses_to_run():
    with pytest.raises(RuntimeError, match="drop and rebuild"):
        CONVERSION.convert(None, None)
