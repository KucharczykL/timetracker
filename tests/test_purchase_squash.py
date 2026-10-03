"""The squash refuses data elided passes needed.

The live tables keep their 0018 names, so the
guard reads them here; `make verify-dump` on a
pre-squash dump runs the real path.
"""

from importlib import import_module
from types import SimpleNamespace

import pytest
from django.db import connection
from django_q.models import Schedule
from entries import record_entry
from purchases import record_purchase

from games.models import ExchangeRate, FilterPreset, Game

SQUASH = import_module(
    "games.migrations."
    "0019_device_access_end_squashed_0036_defer_library_event_stream_matches_library"
)

pytestmark = pytest.mark.django_db

SCHEMA_EDITOR = SimpleNamespace(connection=connection)


def _guard() -> None:
    SQUASH.refuse_unconverted_data(None, SCHEMA_EDITOR)


@pytest.fixture(autouse=True)
def no_stored_rates():
    """The test database loads fixture rates."""
    ExchangeRate.objects.all().delete()


def test_the_guard_runs_first():
    guard, schedule = SQUASH.Migration.operations[:2]
    assert guard.code is SQUASH.refuse_unconverted_data
    assert schedule.code is SQUASH.remove_retired_schedule
    assert guard.elidable and schedule.elidable


def test_empty_tables_pass(owned_library):
    FilterPreset.objects.create(library=owned_library, name="Sessions", mode="sessions")
    _guard()


def test_a_stored_rate_is_refused():
    ExchangeRate.objects.create(
        currency_from="CZK", currency_to="EUR", year=2020, rate="0.04"
    )
    with pytest.raises(RuntimeError, match="games_exchangerate holds"):
        _guard()


def test_a_purchase_row_is_refused(owned_library, stated_graph):
    graph = stated_graph(Game(name="Tunic", library=owned_library), owned_library)
    record_purchase(record_entry(owned_library, graph.release))
    assert not ExchangeRate.objects.exists()
    with pytest.raises(RuntimeError, match="games_purchase holds"):
        _guard()


@pytest.mark.parametrize(
    ("mode", "object_filter"),
    [
        ("purchases", {}),
        ("games", {"purchase_filter": {"price": {"value": 10}}}),
    ],
    ids=["purchases mode", "a purchase relation"],
)
def test_a_purchase_preset_is_refused(owned_library, mode, object_filter):
    FilterPreset.objects.create(
        library=owned_library, name="Old", mode=mode, object_filter=object_filter
    )
    with pytest.raises(RuntimeError, match="games_filterpreset holds"):
        _guard()


def test_the_retired_schedule_goes():
    Schedule.objects.create(func=SQUASH.RETIRED_TASK, schedule_type=Schedule.DAILY)
    Schedule.objects.create(
        func="games.tasks.convert_prices", schedule_type=Schedule.DAILY
    )
    SQUASH.remove_retired_schedule(None, SCHEMA_EDITOR)
    assert list(Schedule.objects.values_list("func", flat=True)) == [
        "games.tasks.convert_prices"
    ]
