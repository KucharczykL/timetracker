"""Day facets read the calendar, not the active zone."""

from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
from calendar_days import (
    displace_calendar,
    library_noon,
    other_displaced_zone,
    process_day,
)
from completed_runs import make_purchase
from devices import create_device
from django.utils import timezone
from session_rows import session_row

from common.criteria import DateCriterion, FieldComparisonCriterion, Modifier
from games.filters import (
    DeviceFilter,
    GameFilter,
    PlatformFilter,
    PlayerSessionFilter,
    PurchaseFilter,
    filter_query_context_for_library,
)
from games.models import Device, Game, Platform, PlayerSession, Purchase
from games.reads.calendar import calendar_today

pytestmark = pytest.mark.django_db(transaction=True)


def _game(library):
    return Game.objects.create(library=library, name="Tunic")


def _purchase(library):
    return make_purchase(library, name="Tunic")


def _platform(library):
    return Platform.objects.create(library=library, name="Deck")


def _device(library):
    return create_device(library=library, name="Deck")


ROWS = {
    Game: (_game, GameFilter),
    Purchase: (_purchase, PurchaseFilter),
    Platform: (_platform, PlatformFilter),
    Device: (_device, DeviceFilter),
}


def _matching(library, model, criterion) -> set:
    _, filter_class = ROWS[model]
    context = filter_query_context_for_library(library)
    rows = context.queryset_for(model)
    return set(rows.filter(filter_class(created_at=criterion).to_q(context)))


@pytest.mark.parametrize("model", list(ROWS), ids=lambda model: model.__name__)
def test_created_at_reads_the_calendar_under_another_active_zone(owned_library, model):
    displaced = displace_calendar(owned_library)
    seed, _ = ROWS[model]
    row = seed(owned_library)
    model.objects.filter(pk=row.pk).update(created_at=library_noon(owned_library))
    calendar_day = calendar_today(owned_library)
    assert calendar_day != process_day()

    with timezone.override(ZoneInfo(other_displaced_zone(displaced))):
        on_the_calendar_day = _matching(
            owned_library, model, DateCriterion(value=calendar_day.isoformat())
        )
        on_the_process_day = _matching(
            owned_library, model, DateCriterion(value=process_day().isoformat())
        )

    assert on_the_calendar_day == {row}
    assert on_the_process_day == set()


HOUR = timedelta(hours=1)


def _sessions(library, session_filter) -> set:
    context = filter_query_context_for_library(library)
    return set(context.queryset_for(PlayerSession).filter(session_filter.to_q(context)))


@pytest.fixture
def displaced_rows(owned_library):
    """Timed, Corrected and Duration-only, at calendar noon."""
    displaced = displace_calendar(owned_library)
    game = Game.objects.create(library=owned_library, name="Tunic")
    noon = library_noon(owned_library)
    timed = session_row(game, started_at=noon, ended_at=noon + HOUR)
    corrected = session_row(
        game, started_at=noon, ended_at=noon + HOUR, duration_manual=HOUR
    )
    written = session_row(game, started_at=noon, duration_manual=HOUR)
    return displaced, timed, corrected, written


@pytest.mark.parametrize("value_of", [calendar_today, lambda library: process_day()])
def test_started_agrees_with_day_on_every_instant_row(
    owned_library, displaced_rows, value_of
):
    displaced, timed, _corrected, written = displaced_rows
    day = DateCriterion(value=value_of(owned_library).isoformat())

    with timezone.override(ZoneInfo(other_displaced_zone(displaced))):
        by_start = _sessions(owned_library, PlayerSessionFilter(started=day))
        by_day = _sessions(owned_library, PlayerSessionFilter(day=day))

    assert by_start == by_day - {written}
    assert (timed in by_start) == (value_of is calendar_today)


def test_a_written_day_has_no_start(owned_library, displaced_rows):
    displaced, _timed, _corrected, written = displaced_rows
    absent = DateCriterion(modifier=Modifier.IS_NULL)

    with timezone.override(ZoneInfo(other_displaced_zone(displaced))):
        assert _sessions(owned_library, PlayerSessionFilter(started=absent)) == {
            written
        }


def test_ended_reads_the_rows_zone(owned_library, displaced_rows):
    displaced, timed, corrected, _written = displaced_rows
    tomorrow = calendar_today(owned_library) + timedelta(days=1)
    before_tomorrow = DateCriterion(
        value=tomorrow.isoformat(), modifier=Modifier.LESS_THAN
    )

    with timezone.override(ZoneInfo(other_displaced_zone(displaced))):
        ended = _sessions(owned_library, PlayerSessionFilter(ended=before_tomorrow))

    assert ended == {timed, corrected}


def test_a_date_granular_comparison_reads_the_calendar(owned_library):
    """One calendar day; two in the other zone."""
    displaced = displace_calendar(owned_library)
    game = Game.objects.create(library=owned_library, name="Tunic")
    noon = library_noon(owned_library)
    half_day = timedelta(hours=11, minutes=30)
    within_the_day = session_row(
        game, started_at=noon - half_day, ended_at=noon + half_day
    )
    same_day = PlayerSessionFilter(
        field_comparisons=[
            FieldComparisonCriterion(
                left="started_at",
                right="ended_at",
                modifier=Modifier.EQUALS,
                granularity="date",
            )
        ]
    )

    with timezone.override(ZoneInfo(other_displaced_zone(displaced))):
        matched = _sessions(owned_library, same_day)

    assert matched == {within_the_day}
