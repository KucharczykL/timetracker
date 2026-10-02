"""The historical legacy purchase."""

# conversion-tooling

from datetime import date
from io import StringIO
from typing import get_args

import pytest
from django.core.management import CommandError, call_command
from django.db import connection
from legacy_purchases import LegacyOwnershipCode, LegacyTypeCode

from games.backfill.legacy_model import LegacyTableGone, require_legacy_table
from games.backfill.purchase_plan import LegacyOwnership, LegacyType
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


def test_a_squashed_state_is_gone_too(monkeypatch):
    from games.backfill import legacy_model

    monkeypatch.setattr(legacy_model, "LEGACY_STATE", ("games", "9999_squashed"))
    legacy_model.legacy_purchase_model.cache_clear()
    try:
        with pytest.raises(LegacyTableGone, match="9999_squashed is no longer on disk"):
            legacy_model.legacy_purchase_model()
    finally:
        legacy_model.legacy_purchase_model.cache_clear()


def test_the_command_refuses_once_the_table_is_gone(owned_user):
    with pytest.raises(
        CommandError, match="Nothing to convert: Table games_legacypurchase is absent"
    ):
        call_command(
            "verify_purchase_conversion",
            "--user",
            owned_user.username,
            stdout=StringIO(),
        )


@pytest.mark.parametrize(
    ("codes", "words"),
    [(LegacyOwnershipCode, LegacyOwnership), (LegacyTypeCode, LegacyType)],
)
def test_the_codes_are_the_stored_words(codes, words):
    stated = {value for name, value in vars(codes).items() if name.isupper()}
    assert stated == set(get_args(words.__value__))
