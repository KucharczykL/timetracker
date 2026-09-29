"""Day facets read the calendar, not the active zone."""

import json
from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
from calendar_days import (
    DISPLACED_ZONES,
    library_noon,
    other_displaced_zone,
    set_calendar,
)
from completed_runs import make_purchase
from devices import create_device
from django.utils import timezone
from historical_playtime_rows import record_row
from session_rows import session_row, tracked_run

from common.criteria import DateCriterion, FieldComparisonCriterion, Modifier
from games.filters import (
    DeviceFilter,
    GameFilter,
    HistoricalPlaytimeFilter,
    PlatformFilter,
    PlayerSessionFilter,
    PlaythroughFilter,
    PurchaseFilter,
    filter_query_context_for_library,
)
from games.models import (
    Device,
    Game,
    HistoricalPlaytime,
    Platform,
    PlayerSession,
    Playthrough,
    Purchase,
)
from games.reads.calendar import calendar_today

pytestmark = pytest.mark.django_db(transaction=True)

HOUR = timedelta(hours=1)


@pytest.fixture(params=DISPLACED_ZONES, ids=lambda zone: zone.split("/")[1])
def calendar(request, owned_library) -> str:
    """The library's calendar, in each displaced zone in turn."""
    return set_calendar(owned_library, request.param)


@pytest.fixture
def elsewhere(calendar) -> ZoneInfo:
    """An active zone never on the calendar's date."""
    return ZoneInfo(other_displaced_zone(calendar))


def _game(library):
    return Game.objects.create(library=library, name="Tunic")


def _run(library):
    return tracked_run(library, _game(library))


def _record(library):
    return record_row([_run(library)])


def _platform(library):
    return Platform.objects.create(library=library, name="Deck")


def _device(library):
    return create_device(library=library, name="Deck")


def _purchase(library):
    return make_purchase(library, name="Tunic")


ROWS = {
    Game: (_game, GameFilter, ("created_at", "updated_at")),
    Purchase: (_purchase, PurchaseFilter, ("created_at", "updated_at")),
    Platform: (_platform, PlatformFilter, ("created_at",)),
    Device: (_device, DeviceFilter, ("created_at",)),
    Playthrough: (_run, PlaythroughFilter, ("created_at",)),
    HistoricalPlaytime: (_record, HistoricalPlaytimeFilter, ("created_at",)),
}

FACETS = [(model, facet) for model, (_, _, facets) in ROWS.items() for facet in facets]


def _matching(library, model, statement) -> set:
    context = filter_query_context_for_library(library)
    return set(context.queryset_for(model).filter(statement.to_q(context)))


@pytest.mark.parametrize(
    ("model", "facet"), FACETS, ids=lambda value: getattr(value, "__name__", value)
)
def test_a_timestamp_facet_reads_the_calendar(owned_library, elsewhere, model, facet):
    seed, filter_class, _ = ROWS[model]
    row = seed(owned_library)
    noon = library_noon(owned_library)
    model.objects.filter(pk=row.pk).update(**{facet: noon})
    calendar_day = calendar_today(owned_library)
    other_day = noon.astimezone(elsewhere).date()
    assert other_day != calendar_day

    with timezone.override(elsewhere):
        on_the_calendar_day = _matching(
            owned_library,
            model,
            filter_class(**{facet: DateCriterion(value=calendar_day.isoformat())}),
        )
        on_the_other_day = _matching(
            owned_library,
            model,
            filter_class(**{facet: DateCriterion(value=other_day.isoformat())}),
        )

    assert on_the_calendar_day == {row}
    assert on_the_other_day == set()


def _sessions(library, session_filter) -> set:
    return _matching(library, PlayerSession, session_filter)


@pytest.fixture
def displaced_rows(owned_library, calendar):
    """Timed, Corrected and Duration-only, at calendar noon."""
    game = _game(owned_library)
    noon = library_noon(owned_library)
    timed = session_row(game, started_at=noon, ended_at=noon + HOUR)
    corrected = session_row(
        game, started_at=noon, ended_at=noon + HOUR, duration_manual=HOUR
    )
    written = session_row(game, started_at=noon, duration_manual=HOUR)
    return timed, corrected, written


def test_started_reads_the_rows_zone(owned_library, elsewhere, displaced_rows):
    timed, corrected, written = displaced_rows
    today = DateCriterion(value=calendar_today(owned_library).isoformat())
    other = DateCriterion(
        value=library_noon(owned_library).astimezone(elsewhere).date().isoformat()
    )

    with timezone.override(elsewhere):
        by_start = _sessions(owned_library, PlayerSessionFilter(started=today))
        by_day = _sessions(owned_library, PlayerSessionFilter(day=today))
        elsewhere_start = _sessions(owned_library, PlayerSessionFilter(started=other))

    assert by_start == {timed, corrected}
    assert by_day == {timed, corrected, written}
    assert elsewhere_start == set()


def test_a_written_day_has_no_start(owned_library, elsewhere, displaced_rows):
    _timed, _corrected, written = displaced_rows
    absent = DateCriterion(modifier=Modifier.IS_NULL)

    with timezone.override(elsewhere):
        assert _sessions(owned_library, PlayerSessionFilter(started=absent)) == {
            written
        }


def test_ended_reads_the_rows_zone(owned_library, elsewhere, displaced_rows):
    timed, corrected, _written = displaced_rows
    today = DateCriterion(value=calendar_today(owned_library).isoformat())

    with timezone.override(elsewhere):
        ended = _sessions(owned_library, PlayerSessionFilter(ended=today))

    assert ended == {timed, corrected}


def _same_day(left: str, right: str) -> FieldComparisonCriterion:
    return FieldComparisonCriterion(
        left=left, right=right, modifier=Modifier.EQUALS, granularity="date"
    )


def test_a_date_granular_comparison_reads_the_calendar(
    owned_library, elsewhere, calendar
):
    """One calendar day; two in the other zone."""
    game = _game(owned_library)
    noon = library_noon(owned_library)
    half_day = timedelta(hours=11, minutes=30)
    within_the_day = session_row(
        game, started_at=noon - half_day, ended_at=noon + half_day
    )
    same_day = PlayerSessionFilter(
        field_comparisons=[_same_day("started_at", "ended_at")]
    )

    with timezone.override(elsewhere):
        matched = _sessions(owned_library, same_day)

    assert matched == {within_the_day}


def test_a_date_operand_meets_a_timestamp_on_the_calendar(
    owned_library, elsewhere, calendar
):
    """The date column stays; the timestamp is read in the calendar."""
    purchase = _purchase(owned_library)
    Purchase.objects.filter(pk=purchase.pk).update(
        date_purchased=calendar_today(owned_library),
        created_at=library_noon(owned_library),
    )
    bought_on_creation = PurchaseFilter(
        field_comparisons=[_same_day("date_purchased", "created_at")]
    )

    with timezone.override(elsewhere):
        matched = _matching(owned_library, Purchase, bought_on_creation)

    assert matched == {purchase}


def test_a_nested_filter_shares_the_calendar(owned_library, elsewhere, calendar):
    game = _game(owned_library)
    noon = library_noon(owned_library)
    session = session_row(game, started_at=noon, ended_at=noon + HOUR)
    PlayerSession.objects.filter(pk=session.pk).update(created_at=noon)
    recorded_today = GameFilter(
        session_filter=PlayerSessionFilter(
            created_at=DateCriterion(value=calendar_today(owned_library).isoformat())
        )
    )

    with timezone.override(elsewhere):
        matched = _matching(owned_library, Game, recorded_today)

    assert matched == {game}


def test_the_session_api_reads_the_calendar(
    client, owned_user, owned_library, calendar
):
    """The request's active zone is the display zone, not the calendar."""
    client.force_login(owned_user)
    game = _game(owned_library)
    noon = library_noon(owned_library)
    session = session_row(game, started_at=noon, ended_at=noon + HOUR)
    PlayerSession.objects.filter(pk=session.pk).update(created_at=noon)

    def listed(day) -> list[str]:
        statement = json.dumps({"created_at": {"modifier": "EQUALS", "value": day}})
        answer = client.get("/api/session/", {"filter": statement}).json()
        return [item["id"] for item in answer["items"]]

    today = calendar_today(owned_library)

    assert listed(today.isoformat()) == [str(session.pk)]
    assert listed((today - timedelta(days=1)).isoformat()) == []
    assert listed((today + timedelta(days=1)).isoformat()) == []
