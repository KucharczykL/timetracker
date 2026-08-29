"""What happens to a referenced row.

The policy is in `docs/event-retention.md`.
"""

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from django.db.models import Exists, Model, OuterRef, QuerySet

from games.events.references import (
    DEFAULT_REFERENCE_KINDS,
    Reference,
    ReferenceKind,
    ReferenceKindRegistry,
    Resolution,
)
from games.models import LibraryEventReference


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
    #: The plain manager. It sees removed rows.
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
            "replay must still be able to resolve them. Take it out of the "
            "library with games.removal.remove, which keeps the row."
        )
