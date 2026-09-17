"""Resolving the row a command's UUID names."""

import uuid
from dataclasses import dataclass

from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Model, QuerySet

from games.events.dispatch import CommandContext, CommandRejected
from games.models import Device


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


def library_device(
    context: CommandContext, device_id: uuid.UUID | None
) -> Device | None:
    """This library's device, or a refusal; None is a device nobody stated."""
    if device_id is None:
        return None
    device = library_row(
        context,
        Device.objects.all(),
        Refusal(
            message=(
                f"This library holds no device {device_id}. A stated fact "
                "names a device the library records."
            ),
            sentence="That device is not available.",
        ),
        pk=device_id,
    )
    #: Under dispatch's lock: the mark cannot move.
    if device.removed_at is not None:
        raise CommandRejected(
            f"This library removed device {device_id}, so nothing names it anew.",
            sentence=(
                "That device was removed from your library. Restore it "
                "before choosing it."
            ),
        )
    return device
