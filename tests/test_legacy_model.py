"""The historical legacy purchase."""

# conversion-tooling

from datetime import date
from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from django.db import connection

from games.backfill.legacy_model import LegacyTableGone, require_legacy_table
from games.models import Game

pytestmark = pytest.mark.django_db


def test_the_fixture_model_takes_keys(owned_library, legacy_purchase):
    game = Game.objects.create(name="Tunic", library=owned_library)

    row = legacy_purchase.objects.create(
        library_id=owned_library.pk,
        date_purchased=date(2021, 5, 3),
        price_currency="EUR",
    )
    row.games.add(game.pk)

    assert list(row.games.values_list("pk", flat=True)) == [game.pk]


def test_the_table_is_gone_without_the_fixture():
    with pytest.raises(LegacyTableGone):
        require_legacy_table(connection)


def test_the_fixture_answers_the_model(legacy_purchase):
    assert require_legacy_table(connection) is legacy_purchase


def test_the_command_refuses_once_the_table_is_gone(owned_user):
    with pytest.raises(CommandError, match="legacy purchase table is gone"):
        call_command(
            "verify_purchase_conversion",
            "--user",
            owned_user.username,
            stdout=StringIO(),
        )
