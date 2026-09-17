"""What every playtime sum shares."""

from datetime import timedelta

from django.db.models import DurationField, Value
from django.db.models.expressions import Combinable, Expression

#: A per-game sum; NULL when unplayed.
type PlaytimeSum = Combinable
#: A per-game figure; never NULL.
type Playtime = Combinable

ZERO = Value(timedelta(0), output_field=DurationField())


class UnscopedPlaytimeRead(RuntimeError):
    """A playtime sum executed without a library."""


class UnscopedSum(Expression):
    """Compiles for validation; refuses to execute."""

    output_field = DurationField()

    def as_sql(self, compiler, connection):
        raise UnscopedPlaytimeRead(
            "A playtime sum was executed without a library; state one."
        )
