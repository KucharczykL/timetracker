"""The legacy rename, forward and back."""

from decimal import Decimal

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

BEFORE = ("games", "0025_playergame_excluded_from_dropped")
AFTER = ("games", "0027_purchase")

pytestmark = pytest.mark.django_db(transaction=True)


def _names(table: str) -> set[str]:
    """Index and constraint names on a table."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT index_class.relname FROM pg_index
            JOIN pg_class index_class ON index_class.oid = pg_index.indexrelid
            JOIN pg_class table_class ON table_class.oid = pg_index.indrelid
            WHERE table_class.relname = %s
            UNION
            SELECT conname FROM pg_constraint
            JOIN pg_class table_class ON table_class.oid = conrelid
            WHERE table_class.relname = %s
            """,
            [table, table],
        )
        return {name for (name,) in cursor.fetchall()}


def _migrate(target: tuple[str, str]) -> None:
    MigrationExecutor(connection).migrate([target])


def test_the_rename_moves_every_name_and_reverses():
    (latest,) = MigrationExecutor(connection).loader.graph.leaf_nodes("games")
    try:
        _migrate(BEFORE)
        legacy = _names("games_purchase") | _names("games_purchase_games")
        assert legacy
        assert not any(name.startswith("games_legacypurchase") for name in legacy)

        _migrate(AFTER)
        renamed = _names("games_legacypurchase") | _names("games_legacypurchase_games")
        assert not any(name.startswith("games_purchase_") for name in renamed)
        assert "live_purchase_per_entry_idx" in _names("games_purchase")
        assert all(len(name) <= 63 for name in renamed)
    finally:
        _migrate(latest)


def _rate() -> object:
    with connection.cursor() as cursor:
        cursor.execute("SELECT rate FROM games_exchangerate WHERE year = 1999")
        ((rate,),) = cursor.fetchall()
        return rate


def test_the_rate_copy_runs_both_ways():
    (latest,) = MigrationExecutor(connection).loader.graph.leaf_nodes("games")
    try:
        _migrate(("games", "0028_purchase_refund"))
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO games_exchangerate (currency_from, currency_to, year, rate)"
                " VALUES ('USD', 'CZK', 1999, 23.123456789012345)"
            )

        _migrate(("games", "0029_exchangerate_decimal_rate"))
        assert _rate() == Decimal("23.123456789012")

        _migrate(("games", "0028_purchase_refund"))
        assert _rate() == 23.123456789012
    finally:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM games_exchangerate WHERE year = 1999")
        _migrate(latest)
