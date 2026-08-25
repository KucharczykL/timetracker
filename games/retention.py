"""What happens to a referenced row.

The policy is in `docs/event-retention.md`.
"""

import contextvars
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from enum import StrEnum
from typing import Any

from django.db import router, transaction
from django.db.models import Exists, Model, OuterRef, QuerySet
from django.db.models.deletion import Collector
from django.utils.timezone import now

from games.events.references import (
    DEFAULT_REFERENCE_KINDS,
    Reference,
    ReferenceKind,
    ReferenceKindRegistry,
    Resolution,
)
from games.models import Game, LibraryEventReference


class ReferencedRowDeletion(Exception):
    """Raised when a referenced row is deleted."""


class UnresolvableReference(LookupError):
    """Raised when a recorded reference names nothing."""

    def __init__(self, reference: Reference) -> None:
        self.reference = reference
        super().__init__(
            f"the recorded reference {reference['kind']}:{reference['id']} "
            f"({reference['label']!r}) names a row that no longer exists. A "
            "REQUIRED reference is retained rather than deleted, so this is a "
            "row that left outside the retention policy."
        )


class Retirement(StrEnum):
    """What retiring a row meant."""

    DELETED = "deleted"
    ARCHIVED = "archived"


def reference_count(
    instance: Model, *, kinds: ReferenceKindRegistry = DEFAULT_REFERENCE_KINDS
) -> int:
    """How many recorded references name this row.

    Not library-scoped. One library keeps a shared row for all.
    """
    kind = kinds.kind_of(instance)
    return LibraryEventReference.objects.to_row(kind.name, instance.pk).count()


def must_be_retained(
    instance: Model, *, kinds: ReferenceKindRegistry = DEFAULT_REFERENCE_KINDS
) -> bool:
    """Whether a delete would strand a reference."""
    kind = kinds.kind_of(instance)
    if kind.resolution is not Resolution.REQUIRED:
        #: EVIDENCE_ONLY: the snapshot promised everything.
        return False
    return LibraryEventReference.objects.to_row(kind.name, instance.pk).exists()


def resolve_reference(
    reference: Reference, *, kinds: ReferenceKindRegistry = DEFAULT_REFERENCE_KINDS
) -> Model:
    """The row a reference names."""
    kind = kinds.kind_for(reference["kind"])
    #: The plain manager. It sees archived rows.
    try:
        return kind.model._default_manager.get(pk=reference["id"])
    except kind.model.DoesNotExist:
        raise UnresolvableReference(reference) from None


def unresolved_among(
    kind: ReferenceKind[Any], references: QuerySet[LibraryEventReference]
) -> QuerySet[LibraryEventReference]:
    """The references of `kind` naming no row."""
    #: `~Exists` plans as an anti-join.
    return references.filter(
        ~Exists(kind.model._default_manager.filter(pk=OuterRef("referenced_id")))
    )


def detach_game_from_purchases(game: Game) -> None:
    """Take a game out of its purchases.

    `m2m_changed` does not fire for a deletion. A purchase with no
    games left is deleted.
    """
    for purchase in game.purchases.all():
        if purchase.num_purchases > 0:
            purchase.num_purchases -= 1
            if purchase.num_purchases == 0:
                purchase.delete()
            else:
                purchase.updated_at = now()
                purchase.save(update_fields=["num_purchases", "updated_at"])


#: What a delete does that no cascade does.
#: Archiving never fires the `pre_delete` receiver.
_UNCASCADED_COLLATERAL: dict[type[Model], Callable[[Any], None]] = {
    Game: detach_game_from_purchases,
}


def archive_or_delete(instance: Model) -> Retirement:
    """Delete the row, or archive it."""
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
        #: A stamp, not an edit.
        #: `save()` would run `clean()` and a receiver.
        model._default_manager.filter(pk=instance.pk).update(archived_at=stamp)
        instance.archived_at = stamp  # type: ignore[attr-defined]
        return Retirement.ARCHIVED


def _delete_everything_but(instance: Model) -> None:
    """Run the delete, and keep the row."""
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
    #: The guard rules this out.
    #: Do not depend on that.
    collector.fast_deletes = [
        queryset.exclude(pk=instance.pk) if queryset.model is model else queryset
        for queryset in collector.fast_deletes
    ]
    collector.delete()


_purging = contextvars.ContextVar("purging_library", default=False)


@contextmanager
def purging_library() -> Iterator[None]:
    """Let a whole-library purge delete referenced rows.

    A purge takes the events too. Nothing is left to resolve.
    """
    token = _purging.set(True)
    try:
        yield
    finally:
        _purging.reset(token)


def refuse_to_delete_a_referenced_row(instance: Model) -> None:
    """The guard, called from `pre_delete`."""
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
