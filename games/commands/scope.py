"""Resolving the row a command's UUID names."""

import uuid
from dataclasses import dataclass

from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Model, QuerySet

from games.events.dispatch import CommandContext, CommandRejected, RowNotHeld
from games.models import Device


@dataclass(frozen=True, slots=True)
class Refusal:
    """What a caller says when nothing resolves.

    `message` reaches a log and may name an id.
    `sentence` is the only thing a person sees.
    """

    message: str
    #: Only a refusal states one.
    sentence: str | None = None
    #: A rejection refuses; the default answers absent.
    raises: type[RowNotHeld | CommandRejected] = RowNotHeld

    def __post_init__(self) -> None:
        absent = issubclass(self.raises, RowNotHeld)
        if absent and self.sentence is not None:
            raise TypeError(
                f"{self.raises.__name__} shows no sentence. State a "
                "CommandRejected subclass beside it, or take it away."
            )
        if not absent and self.sentence is None:
            raise TypeError(
                f"{self.raises.__name__} reaches a person. State a sentence "
                "naming the remedy, or let `raises` default to RowNotHeld."
            )

    def raised(self) -> RowNotHeld | CommandRejected:
        #: RowNotHeld holds no sentence keyword.
        if issubclass(self.raises, RowNotHeld):
            return self.raises(self.message)
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


def library_device_row(
    context: CommandContext, device_id: uuid.UUID | None
) -> Device | None:
    """This library's device, removed or not; None unstated."""
    if device_id is None:
        return None
    return library_row(
        context,
        Device.objects.all(),
        Refusal(
            message=(
                f"This library holds no device {device_id}. A stated fact "
                "names a device the library records."
            )
        ),
        pk=device_id,
    )


def library_device(
    context: CommandContext, device_id: uuid.UUID | None
) -> Device | None:
    """This library's live device, or a refusal."""
    device = library_device_row(context, device_id)
    if device is None:
        return None
    #: Under dispatch's lock; mark cannot move.
    if device.removed_at is not None:
        raise CommandRejected(
            f"This library removed device {device_id}, so nothing names it anew.",
            sentence=(
                "That device was removed from your library. Restore it "
                "before choosing it."
            ),
        )
    return device
