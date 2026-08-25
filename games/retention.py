"""What happens to a catalog row a recorded event named.

`docs/event-references.md` promises that a `REQUIRED` reference resolves: a
replay reading a payload must find the row it names. Nothing enforced that
promise -- the three delete views hard-deleted, and a recorded reference could
be left pointing at nothing.

This module is the policy that keeps it. A row no event named is really
deleted, as before. A row an event named is *retired* instead: everything the
delete would have taken with it still goes, and the row itself stays behind
with `archived_at` set, out of sight of every library-scoped read but still
resolvable by id.

The two halves are deliberately separate. Retention and resolvability live
here; failing a replay that cannot resolve a reference, and reporting why, is
#669's.
"""

import contextvars
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from enum import StrEnum
from typing import Any

from django.db import router, transaction
from django.db.models import Model
from django.db.models.deletion import Collector
from django.utils.timezone import now

from games.events.references import (
    DEFAULT_REFERENCE_KINDS,
    Reference,
    ReferenceKindRegistry,
    Resolution,
)
from games.models import Game, LibraryEventReference


class ReferencedRowDeletion(Exception):
    """Raised when something tries to delete a row an event references.

    The three delete views go through `archive_or_delete` and never see this.
    It exists for everything else -- a shell, a script, a management command --
    because a promise only one call path keeps is not a promise.
    """


class UnresolvableReference(LookupError):
    """Raised when a recorded reference names a row that is not there.

    Carries the kind and id rather than only a message, so #669's
    reconciliation report can be built from the exception instead of by
    re-reading the payload.
    """

    def __init__(self, reference: Reference) -> None:
        self.reference = reference
        super().__init__(
            f"the recorded reference {reference['kind']}:{reference['id']} "
            f"({reference['label']!r}) names a row that no longer exists. A "
            "REQUIRED reference is retained rather than deleted, so this is a "
            "row that left outside the retention policy."
        )


class Retirement(StrEnum):
    """What retiring a row turned out to mean."""

    DELETED = "deleted"
    ARCHIVED = "archived"


def reference_count(
    instance: Model, *, kinds: ReferenceKindRegistry = DEFAULT_REFERENCE_KINDS
) -> int:
    """How many recorded references name this row.

    Deliberately not library-scoped: a shared Platform one library referenced
    is retained for every library, because the event that named it outlives
    whichever library stops using it.
    """
    kind = kinds.kind_of(instance)
    return LibraryEventReference.objects.to_row(kind.name, instance.pk).count()


def must_be_retained(
    instance: Model, *, kinds: ReferenceKindRegistry = DEFAULT_REFERENCE_KINDS
) -> bool:
    """Whether deleting this row would break a promise a payload made."""
    kind = kinds.kind_of(instance)
    if kind.resolution is not Resolution.REQUIRED:
        #: An EVIDENCE_ONLY reference is a snapshot for a reader, not a
        #: pointer a replay follows. The payload already holds everything it
        #: promised, so the row is free to go.
        return False
    return LibraryEventReference.objects.to_row(kind.name, instance.pk).exists()


def resolve_reference(
    reference: Reference, *, kinds: ReferenceKindRegistry = DEFAULT_REFERENCE_KINDS
) -> Model:
    """The row a recorded reference names, archived or not.

    This is the one read that must see through the archive: the whole point of
    retaining a row is that this keeps working after the library deleted it.
    """
    kind = kinds.kind_for(reference["kind"])
    #: `_default_manager` rather than `objects`, the documented way to reach a
    #: manager on a model you were handed. It is the plain one on all three, so
    #: it sees archived rows -- which is the whole point.
    try:
        return kind.model._default_manager.get(pk=reference["id"])
    except kind.model.DoesNotExist:
        raise UnresolvableReference(reference) from None


def detach_game_from_purchases(game: Game) -> None:
    """Take a game out of the purchases that counted it.

    `m2m_changed` does not fire for a related object's deletion, so the count
    is maintained here. A purchase left with no games at all is deleted: it
    recorded buying something that is no longer in the library.
    """
    for purchase in game.purchases.all():
        if purchase.num_purchases > 0:
            purchase.num_purchases -= 1
            if purchase.num_purchases == 0:
                purchase.delete()
            else:
                purchase.updated_at = now()
                purchase.save(update_fields=["num_purchases", "updated_at"])


#: What a delete does that no cascade describes, per model. Only Game has any:
#: its purchase bookkeeping lives in a `pre_delete` receiver, and archiving
#: never deletes the row, so the receiver never runs.
_UNCASCADED_COLLATERAL: dict[type[Model], Callable[[Any], None]] = {
    Game: detach_game_from_purchases,
}


def archive_or_delete(instance: Model) -> Retirement:
    """Delete the row, or retire it in place if an event named it."""
    with transaction.atomic():
        if not must_be_retained(instance):
            instance.delete()
            return Retirement.DELETED
        model = type(instance)
        collateral = _UNCASCADED_COLLATERAL.get(model)
        if collateral is not None:
            collateral(instance)
        _delete_everything_but(instance)
        stamp = now()
        #: A queryset update rather than `save()`: this is a stamp, not an
        #: edit. `Platform.save()` re-runs `clean()`, and `Game.save()` goes
        #: through the status-change receiver -- neither has anything to say
        #: about a row leaving the library.
        model._default_manager.filter(pk=instance.pk).update(archived_at=stamp)
        instance.archived_at = stamp  # type: ignore[attr-defined]
        return Retirement.ARCHIVED


def _delete_everything_but(instance: Model) -> None:
    """Run the delete this row would have caused, and keep the row.

    Django's own collector decides what a delete takes with it -- which
    relations cascade, which are set to NULL, which m2m rows go. Asking it and
    then dropping the root from what it collected is what keeps archiving and
    deleting the same act minus one row. Enumerating the collateral here by
    hand would be a second copy of every `on_delete`, free to drift from the
    first, and the drift would show up as orphaned sessions in a list.
    """
    model = type(instance)
    collector = Collector(using=router.db_for_write(model, instance=instance))
    collector.collect([instance])
    collected = collector.data.get(model)
    if collected is not None:
        remaining = {row for row in collected if row.pk != instance.pk}
        if remaining:
            collector.data[model] = remaining
        else:
            del collector.data[model]
    #: The root cannot reach a fast-delete queryset while the retention guard
    #: is connected -- a signal listener rules it out -- but the exclusion
    #: costs one clause and does not depend on that staying true.
    collector.fast_deletes = [
        queryset.exclude(pk=instance.pk) if queryset.model is model else queryset
        for queryset in collector.fast_deletes
    ]
    collector.delete()


_purging = contextvars.ContextVar("purging_library", default=False)


@contextmanager
def purging_library() -> Iterator[None]:
    """Let a whole-library purge delete rows the guard would otherwise keep.

    A purge takes the events as well, so after it there is no recorded
    reference left to resolve and nothing to retain the row for. Without this
    the guard would make `delete_user_library` impossible to complete, which is
    the one operation that is allowed to leave nothing behind.
    """
    token = _purging.set(True)
    try:
        yield
    finally:
        _purging.reset(token)


def refuse_to_delete_a_referenced_row(instance: Model) -> None:
    """The guard, called from `pre_delete` on every retainable model."""
    if _purging.get():
        return
    if must_be_retained(instance):
        raise ReferencedRowDeletion(
            f"{instance} cannot be deleted: "
            f"{reference_count(instance)} recorded event(s) reference it, and a "
            "replay must still be able to resolve them. Retire it with "
            "games.retention.archive_or_delete, which removes it from the "
            "library and keeps the row."
        )
