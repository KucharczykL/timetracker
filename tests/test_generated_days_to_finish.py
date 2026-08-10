from datetime import date

import pytest
from django.db import connection, models
from django.db.models import F
from django.db.models.expressions import RawSQL

from games.models import Game, PlayEvent

pytestmark = pytest.mark.django_db


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
def test_generated_days_to_finish(started, ended, expected_days):
    event = PlayEvent.objects.create(
        game=Game.objects.create(name=f"Game {started}-{ended}"),
        started=started,
        ended=ended,
    )
    event.refresh_from_db()

    assert event.days_to_finish == expected_days


def test_days_to_finish_uses_typed_source_columns():
    field = PlayEvent._meta.get_field("days_to_finish")
    references = {
        expression.name
        for expression in field.expression.flatten()
        if isinstance(expression, F)
    }
    sql, _ = field.generated_sql(connection)

    assert field.db_persist is True
    assert isinstance(field.output_field, models.IntegerField)
    assert not isinstance(field.expression, RawSQL)
    assert references == {"started", "ended"}
    assert '"ENDED" -' in sql.upper()
