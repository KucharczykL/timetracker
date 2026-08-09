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
