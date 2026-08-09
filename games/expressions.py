from django.db import models
from django.db.models.expressions import CombinedExpression, Expression


class DatabaseDurationSum(CombinedExpression):
    """Add two durations without SQLite's text-returning duration helper.

    PostgreSQL accepts the resulting interval addition directly. SQLite stores
    durations as integer microseconds, so direct addition also preserves the
    DurationField representation there until PostgreSQL-only cutover.
    """

    def __init__(self, lhs, rhs):
        super().__init__(lhs, "+", rhs, output_field=models.DurationField())

    def resolve_expression(
        self, query=None, allow_joins=True, reuse=None, summarize=False, for_save=False
    ):
        return Expression.resolve_expression(
            self, query, allow_joins, reuse, summarize, for_save
        )


class DatabaseDateDifference(CombinedExpression):
    """Subtract two dates as whole days on each supported database."""

    def __init__(self, lhs, rhs):
        super().__init__(lhs, "-", rhs, output_field=models.IntegerField())

    def as_sqlite(self, compiler, connection):
        lhs_sql, lhs_params = compiler.compile(self.lhs)
        rhs_sql, rhs_params = compiler.compile(self.rhs)
        return (
            f"CAST(julianday({lhs_sql}) - julianday({rhs_sql}) AS integer)",
            [*lhs_params, *rhs_params],
        )

    def resolve_expression(
        self, query=None, allow_joins=True, reuse=None, summarize=False, for_save=False
    ):
        return Expression.resolve_expression(
            self, query, allow_joins, reuse, summarize, for_save
        )
