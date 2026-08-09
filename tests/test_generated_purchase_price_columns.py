from datetime import date

import pytest
from django.db import connection, models
from django.db.models import F

from games.models import Game, Purchase

pytestmark = pytest.mark.django_db


def test_price_per_game_is_null_until_games_are_linked():
    purchase = Purchase.objects.create(
        date_purchased=date(2026, 8, 9),
        price=12,
        price_currency="USD",
    )
    purchase.refresh_from_db()

    assert purchase.num_purchases == 0
    assert purchase.price_per_game is None

    purchase.games.set(
        [Game.objects.create(name="Hades"), Game.objects.create(name="Celeste")]
    )
    purchase.refresh_from_db()

    assert purchase.num_purchases == 2
    assert purchase.price_per_game == 6


def test_price_per_game_still_prefers_converted_price():
    purchase = Purchase.objects.create(
        date_purchased=date(2026, 8, 9),
        price=12,
        converted_price=15,
        price_currency="USD",
        converted_currency="USD",
    )
    purchase.games.set(
        [Game.objects.create(name="Hollow Knight"), Game.objects.create(name="Tunic")]
    )
    purchase.refresh_from_db()

    assert purchase.price_per_game == 7.5


def test_price_per_game_uses_guarded_source_columns():
    field = Purchase._meta.get_field("price_per_game")
    references = {
        expression.name
        for expression in field.expression.flatten()
        if isinstance(expression, F)
    }
    sql, _ = field.generated_sql(connection)

    assert field.db_persist is True
    assert isinstance(field.output_field, models.FloatField)
    assert references == {"converted_price", "price", "num_purchases"}
    assert "NULLIF" in sql.upper()
