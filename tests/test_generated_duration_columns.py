from datetime import UTC, datetime, timedelta

import pytest
from django.db import connection, models
from django.db.models import F

from games.models import Game, Session

pytestmark = pytest.mark.django_db


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
def test_generated_duration_values(
    timestamp_end, duration_manual, expected_calculated, expected_total
):
    session = Session.objects.create(
        game=Game.objects.create(name="Hades"),
        timestamp_start=datetime(2026, 1, 1, 10, tzinfo=UTC),
        timestamp_end=timestamp_end,
        duration_manual=duration_manual,
    )
    session.refresh_from_db()
    assert session.duration_calculated == expected_calculated
    assert session.duration_total == expected_total


def test_duration_total_uses_only_source_columns():
    field = Session._meta.get_field("duration_total")
    references = {
        expression.name
        for expression in field.expression.flatten()
        if isinstance(expression, F)
    }
    assert field.db_persist is True
    assert isinstance(field.output_field, models.DurationField)
    assert references == {"timestamp_end", "timestamp_start", "duration_manual"}
    sql, _ = field.generated_sql(connection)
    assert "django_format_dtdelta" not in sql
