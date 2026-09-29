"""A day facet reads the library calendar, not the active zone."""

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

from common.criteria import DateCriterion
from games.filters import (
    DeviceFilter,
    GameFilter,
    PlatformFilter,
    PurchaseFilter,
    filter_query_context_for_library,
)
from games.models import Device, Game, Platform, Purchase
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
