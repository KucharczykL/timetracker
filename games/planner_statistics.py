"""Planner statistics for tables a bulk write just filled."""

from collections.abc import Iterable

from django.db import connection
from django.db.models import Model


def analyze_tables(tables: Iterable[type[Model]]) -> None:
    """Analyze these tables; autovacuum runs late.

    Named tables only: `DATABASE_URL` may name the deployment.
    """
    named = ", ".join(
        dict.fromkeys(
            connection.ops.quote_name(model._meta.db_table) for model in tables
        )
    )
    if not named:
        return
    with connection.cursor() as cursor:
        cursor.execute(f"ANALYZE {named}")
