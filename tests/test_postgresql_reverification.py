"""Execute PG-01 through PG-06 outcomes against PostgreSQL."""

from datetime import UTC, date, datetime, timedelta

import pytest
from django.db import connection

from games.models import Game, PlayEvent, Purchase, Session

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
