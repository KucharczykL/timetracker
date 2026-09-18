"""What every playtime sum shares."""

from dataclasses import dataclass
from datetime import timedelta
from typing import Final, NewType

from django.db.models import DurationField, Value
from django.db.models.expressions import Combinable, Expression
from django.db.models.functions import Coalesce

from games.reads.unscoped import UnscopedRead

#: A per-game sum; NULL when unplayed.
type PlaytimeSum = Combinable
#: A per-game figure; never NULL.
Playtime = NewType("Playtime", Combinable)

ZERO: Final = Value(timedelta(0), output_field=DurationField())


@dataclass(frozen=True, slots=True)
class PlaytimeBreakdown:
    """Tracked sessions beside historical records."""

    tracked: timedelta
    historical: timedelta

    @property
    def total(self) -> timedelta:
        return self.tracked + self.historical


class UnscopedPlaytimeRead(UnscopedRead):
    """A playtime sum executed without a library."""


class UnscopedSum(Expression):
    """Compiles for validation; refuses to execute."""

    output_field = DurationField()

    def as_sql(self, compiler, connection):
        raise UnscopedPlaytimeRead(
            "A playtime sum was executed without a library; state one."
        )


def zero_when_null(figure: PlaytimeSum) -> Playtime:
    return Playtime(Coalesce(figure, ZERO, output_field=DurationField()))
