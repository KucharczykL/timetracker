"""The query context carries the calendar zone."""

from zoneinfo import ZoneInfo

import pytest
from calendar_days import displace_calendar

from common.criteria import FilterQueryContext, with_filter_aliases
from games.filters import filter_query_context_for_library
from games.reads.calendar import calendar_day_zone


def _unrestricted(model):
    return with_filter_aliases(model._default_manager.all())


def test_a_context_states_its_zone():
    with pytest.raises(TypeError):
        FilterQueryContext(_unrestricted)  # type: ignore[call-arg]


def test_the_validation_context_compiles_in_utc_and_never_executes():
    context = FilterQueryContext.for_validation()

    assert context.calendar_zone == ZoneInfo("UTC")
    with pytest.raises(RuntimeError):
        context.ensure_execution()


def test_the_zone_is_read_once():
    calls: list[int] = []

    def zone() -> ZoneInfo:
        calls.append(1)
        return ZoneInfo("Pacific/Niue")

    context = FilterQueryContext(_unrestricted, day_zone=zone)

    assert context.calendar_zone == context.calendar_zone
    assert calls == [1]


@pytest.mark.django_db(transaction=True)
def test_the_library_context_reads_the_calendar(
    owned_library, django_assert_num_queries
):
    displaced = displace_calendar(owned_library)

    context = filter_query_context_for_library(owned_library)

    with django_assert_num_queries(1):
        assert context.calendar_zone == ZoneInfo(displaced)
        assert context.calendar_zone == ZoneInfo(displaced)
    assert context.calendar_zone == calendar_day_zone(owned_library)
