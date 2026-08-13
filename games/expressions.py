from django.db import models
from django.db.models.expressions import CombinedExpression, Expression


class DatabaseDurationSum(CombinedExpression):
    """Add two PostgreSQL intervals with an explicit DurationField result."""

    def __init__(self, lhs, rhs):
        super().__init__(lhs, "+", rhs, output_field=models.DurationField())

    def resolve_expression(
        self, query=None, allow_joins=True, reuse=None, summarize=False, for_save=False
    ):
        return Expression.resolve_expression(
            self, query, allow_joins, reuse, summarize, for_save
        )


class DatabaseDateDifference(CombinedExpression):
    """Subtract two PostgreSQL dates as a whole-day integer."""

    def __init__(self, lhs, rhs):
        super().__init__(lhs, "-", rhs, output_field=models.IntegerField())

    def resolve_expression(
        self, query=None, allow_joins=True, reuse=None, summarize=False, for_save=False
    ):
        return Expression.resolve_expression(
            self, query, allow_joins, reuse, summarize, for_save
        )
