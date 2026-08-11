"""Execute PG-01 through PG-06 outcomes against PostgreSQL."""

from datetime import UTC, date, datetime, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, transaction

from games.filters import FindFilter
from games.models import FilterPreset, Game, Platform, PlayEvent, Purchase, Session
from games.sorting import GAME_DEFAULT_SORT, GAME_SORTS, apply_sort
from timetracker.postgres_contract import validate_postgres_collation_contract

pytestmark = pytest.mark.django_db


def assert_postgresql() -> None:
    """Reject SQLite: this module is evidence for the PostgreSQL outcomes."""
    assert connection.vendor == "postgresql"


@pytest.mark.parametrize(
    ("timestamp_end", "duration_manual", "expected_calculated", "expected_total"),
    [
        (
            datetime(2026, 1, 1, 12, tzinfo=UTC),
            timedelta(0),
            timedelta(hours=2),
            timedelta(hours=2),
        ),
        (None, timedelta(hours=3), timedelta(0), timedelta(hours=3)),
        (
            datetime(2026, 1, 1, 12, tzinfo=UTC),
            timedelta(minutes=30),
            timedelta(hours=2),
            timedelta(hours=2, minutes=30),
        ),
    ],
)
def test_postgresql_generated_session_durations(
    timestamp_end, duration_manual, expected_calculated, expected_total
):
    """PG-01 generated durations build and compute on PostgreSQL."""
    assert_postgresql()
    session = Session.objects.create(
        game=Game.objects.create(name="Hades"),
        timestamp_start=datetime(2026, 1, 1, 10, tzinfo=UTC),
        timestamp_end=timestamp_end,
        duration_manual=duration_manual,
    )

    session.refresh_from_db()

    assert session.duration_calculated == expected_calculated
    assert session.duration_total == expected_total


def test_postgresql_generated_purchase_price():
    """PG-02's zero guard and converted-price precedence run on PostgreSQL."""
    assert_postgresql()
    purchase = Purchase.objects.create(
        date_purchased=date(2026, 8, 10), price=12, price_currency="USD"
    )
    purchase.refresh_from_db()

    assert purchase.num_purchases == 0
    assert purchase.price_per_game is None

    purchase.games.set(
        [Game.objects.create(name="Celeste"), Game.objects.create(name="Hades")]
    )
    purchase.refresh_from_db()

    assert (purchase.num_purchases, purchase.price_per_game) == (2, 6)

    converted_purchase = Purchase.objects.create(
        date_purchased=date(2026, 8, 10),
        price=12,
        converted_price=15,
        price_currency="USD",
        converted_currency="USD",
    )
    converted_purchase.games.set(
        [
            Game.objects.create(name="Hollow Knight"),
            Game.objects.create(name="Tunic"),
        ]
    )
    converted_purchase.refresh_from_db()

    assert converted_purchase.price_per_game == 7.5


@pytest.mark.parametrize(
    ("started", "ended", "expected_days"),
    [
        (None, None, 0),
        (None, date(2026, 1, 4), 0),
        (date(2026, 1, 1), None, 0),
        (date(2026, 1, 1), date(2026, 1, 1), 1),
        (date(2026, 1, 1), date(2026, 1, 4), 3),
        (date(2026, 1, 4), date(2026, 1, 1), -3),
    ],
)
def test_postgresql_generated_days_to_finish(started, ended, expected_days):
    """PG-03 generated date differences build and compute on PostgreSQL."""
    assert_postgresql()
    event = PlayEvent.objects.create(
        game=Game.objects.create(name=f"Game {started}-{ended}"),
        started=started,
        ended=ended,
    )

    event.refresh_from_db()

    assert event.days_to_finish == expected_days


def test_postgresql_nullable_sorting_is_null_last_and_tie_stable():
    """PG-04's direct and aggregate ordering contract runs on PostgreSQL."""
    assert_postgresql()
    platform = Platform.objects.create(name="P", icon="p")
    unknown = Game.objects.create(name="Unknown", platform=platform)
    early = Game.objects.create(name="Early", platform=platform, year_released=1990)
    late = Game.objects.create(name="Late", platform=platform, year_released=2000)
    first = Game.objects.create(name="First", platform=platform)
    second = Game.objects.create(name="Second", platform=platform)

    ascending = apply_sort(
        Game.objects.all(), FindFilter(sort="year"), GAME_SORTS, GAME_DEFAULT_SORT
    )
    descending = apply_sort(
        Game.objects.all(), FindFilter(sort="-year"), GAME_SORTS, GAME_DEFAULT_SORT
    )

    assert list(ascending.queryset) == [early, late, unknown, first, second]
    assert list(descending.queryset) == [late, early, unknown, first, second]

    tied = apply_sort(
        Game.objects.filter(pk__in=[second.pk, first.pk]),
        FindFilter(sort="status"),
        GAME_SORTS,
        GAME_DEFAULT_SORT,
    )

    assert list(tied.queryset) == [first, second]

    PlayEvent.objects.create(
        game=early, started=date(2026, 1, 1), ended=date(2026, 1, 1)
    )
    PlayEvent.objects.create(
        game=late, started=date(2026, 1, 1), ended=date(2026, 1, 2)
    )
    finished_ascending = apply_sort(
        Game.objects.all(), FindFilter(sort="finished"), GAME_SORTS, GAME_DEFAULT_SORT
    )
    finished_descending = apply_sort(
        Game.objects.all(),
        FindFilter(sort="-finished"),
        GAME_SORTS,
        GAME_DEFAULT_SORT,
    )

    assert list(finished_ascending.queryset) == [early, late, unknown, first, second]
    assert list(finished_descending.queryset) == [late, early, unknown, first, second]


def test_postgresql_connection_satisfies_collation_contract():
    """PG-05 validates the actual PostgreSQL test database."""
    assert_postgresql()
    connection.ensure_connection()
    raw_connection = connection.connection
    assert raw_connection is not None

    contract = validate_postgres_collation_contract(raw_connection)

    assert contract.server_version_num // 10_000 == 18
    assert contract.encoding == "UTF8"
    assert contract.locale_provider == "b"
    assert contract.locale == "C.UTF-8"


def test_postgresql_interval_querysets_partition_sessions():
    """PG-06's interval equality paths execute against PostgreSQL intervals."""
    assert_postgresql()
    game = Game.objects.create(name="Interval game")
    manual_only = Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 1, 1, 12, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 1, 12, tzinfo=UTC),
        duration_manual=timedelta(minutes=30),
    )
    elapsed = Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 1, 2, 12, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 2, 13, tzinfo=UTC),
    )

    assert list(Session.objects.only_manual()) == [manual_only]
    assert list(Session.objects.without_manual()) == [elapsed]


def test_postgresql_json_persistence_and_preset_constraint():
    """PG-06 JSON persistence and declarative constraints execute on PostgreSQL."""
    assert_postgresql()
    user = get_user_model().objects.create_user(
        username="postgres-reverify", password="pw"
    )
    find_filter = {"sort": "-year"}
    object_filter = {"year": {"modifier": "EQUALS", "value": 2026}}
    ui_options = {"per_page": 50}
    preset = FilterPreset.objects.create(
        user=user,
        name="PostgreSQL",
        mode="games",
        find_filter=find_filter,
        object_filter=object_filter,
        ui_options=ui_options,
    )

    preset.refresh_from_db()

    assert preset.find_filter == find_filter
    assert preset.object_filter == object_filter
    assert preset.ui_options == ui_options

    with pytest.raises(IntegrityError), transaction.atomic():
        FilterPreset.objects.create(user=user, name="PostgreSQL", mode="games")
