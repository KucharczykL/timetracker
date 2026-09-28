"""What acts on the Platforms list share; declares no act."""

import uuid
from collections.abc import Callable, Sequence

from django.contrib.auth.models import User
from django.db.models import QuerySet

from games.batch_ledger import ActName
from games.bulk_actions import FilterJson, Resolution, RowOutcome, UndoRow
from games.bulk_narrowing import narrowed
from games.bulk_sessions import lost
from games.events.dispatch import RowNotHeld
from games.events.idempotency import IdempotencyKey
from games.filters import parse_platform_filter
from games.models import Platform, UserLibrary
from games.writes.answers import answered
from games.writes.platform import Moved, undo_platform_batch

PLATFORM_GONE = "One of the platforms is no longer available, so it was left as it is."

#: What a resolve adds to the rows it reads.
type Annotating = Callable[[QuerySet[Platform], UserLibrary], QuerySet[Platform]]


def platform_scope(library: UserLibrary, filter_json: FilterJson) -> QuerySet[Platform]:
    """The list's own read: private, live."""
    return narrowed(
        Platform.objects.for_library(library),
        library,
        filter_json,
        parse_platform_filter,
    )


def platform_resolution(
    library: UserLibrary,
    keys: Sequence[uuid.UUID],
    annotating: Annotating | None = None,
) -> Resolution[Platform]:
    """Keys to live private platforms, name order."""
    wanted = list(dict.fromkeys(keys))
    found = Platform.objects.for_library(library).filter(pk__in=wanted)
    if annotating is not None:
        found = annotating(found, library)
    rows = tuple(found.order_by("name", "id"))
    return Resolution(
        rows, tuple(lost(wanted, {row.pk for row in rows}, PLATFORM_GONE))
    )


def outcome(moved: Moved) -> RowOutcome:
    return RowOutcome.MOVED if moved else RowOutcome.UNCHANGED


def _held_platform(actor: User, key: uuid.UUID) -> Platform:
    """Live or removed, the library's own."""
    with answered("platform"):
        row = Platform.objects.filter(library=actor.library, pk=key).first()
        if row is None:
            raise RowNotHeld(
                f"Platform {key} is not library {actor.library.pk}'s, so the "
                "batch's inverse has no row to write back."
            )
    return row


def undoing(act: ActName) -> UndoRow:
    """The one inverse of every platform act."""

    def undo_one_platform(
        actor: User,
        platform_id: uuid.UUID,
        *,
        undoes: uuid.UUID,
        idempotency_key: IdempotencyKey,
        correlation_id: uuid.UUID,
    ) -> RowOutcome:
        return outcome(
            undo_platform_batch(
                _held_platform(actor, platform_id),
                undoes=undoes,
                batch=correlation_id,
                act=act,
            )
        )

    return undo_one_platform
