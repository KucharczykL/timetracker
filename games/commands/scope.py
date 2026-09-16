"""Resolving the row a command's UUID names."""

from dataclasses import dataclass

from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Model, QuerySet

from games.events.dispatch import CommandContext, CommandRejected


@dataclass(frozen=True, slots=True)
class Refusal:
    """What a caller says when nothing resolves.

    `message` reaches a log and may name an id.
    `sentence` is the only thing a person sees.
    """

    message: str
    sentence: str
    #: A subclass for a separately answered case.
    raises: type[CommandRejected] = CommandRejected

    def raised(self) -> CommandRejected:
        return self.raises(self.message, sentence=self.sentence)


def library_row[RowT: Model](
    context: CommandContext,
    reads: QuerySet[RowT],
    refusal: Refusal,
    **lookup: object,
) -> RowT:
    """This library's row, or a refusal.

    Returns a removed row: every restore names one.

    The lookup must be unique. MultipleObjectsReturned is not
    caught: a second row is a defect, and its traceback is the
    answer to one.
    """
    try:
        return reads.get(library=context.library, **lookup)
    #: A generic queryset cannot name the class.
    except ObjectDoesNotExist:
        raise refusal.raised() from None
