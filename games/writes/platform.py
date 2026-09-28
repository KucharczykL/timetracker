"""A platform removed and restored, locked first."""

import uuid

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.db.models.functions import Lower, Trim

from common.naming import name_key
from games.models import Platform
from games.removal import remove, restore
from games.writes.answers import CONFLICT_STATUS, CommandFailed

#: Whether the write changed the row.
type Moved = bool


#: The constraints a restore answers as a taken name.
NAME_CONSTRAINTS = frozenset(
    {
        "unique_private_platform_normalized_name_group",
        "unique_shared_platform_normalized_name_group",
    }
)


def taken_sentence(platform: Platform) -> str:
    """Why this platform cannot come back."""
    return (
        f"{platform.named_with_group} cannot come back: another platform "
        "with that name is in your library now. Rename or remove that one "
        "first."
    )


def removed_again_sentence(platform: Platform) -> str:
    """Why a batch's Undo leaves it removed."""
    return (
        f"{platform.named_with_group} was removed again since, so it was left as it is."
    )


def _refuse_a_taken_name(platform: Platform) -> None:
    """A live platform, private or shared, holding its name.

    The constraints compare private with private and shared with
    shared; `clean()` refuses a private row shadowing a shared one,
    and a stamp calls no `clean()`.
    """
    taken = (
        Platform.objects.alive()
        .exclude(pk=platform.pk)
        .filter(Q(library__isnull=True) | Q(library=platform.library_id))
        .annotate(
            normalized_name=Lower(Trim("name")),
            normalized_group=Lower(Trim("group")),
        )
        .filter(
            normalized_name=name_key(platform.name),
            normalized_group=name_key(platform.group),
        )
    )
    if taken.exists():
        raise CommandFailed(taken_sentence(platform), CONFLICT_STATUS)


def _constraint_of(collision: IntegrityError) -> str | None:
    diagnostic = getattr(collision.__cause__, "diag", None)
    return None if diagnostic is None else diagnostic.constraint_name


def _restore(platform: Platform) -> None:
    """Put it back, or refuse with a sentence.

    A name constraint here is an insert racing the check; any other
    rises as itself, a defect.
    """
    _refuse_a_taken_name(platform)
    try:
        restore(platform)
    except IntegrityError as collision:
        if _constraint_of(collision) not in NAME_CONSTRAINTS:
            raise
        raise CommandFailed(taken_sentence(platform), CONFLICT_STATUS) from collision


def _locked(platform: Platform) -> Platform:
    return Platform.objects.select_for_update().get(pk=platform.pk)


def remove_platform_in_batch(platform: Platform, *, batch: uuid.UUID) -> Moved:
    """Take a live row out, naming the batch.

    A live row already naming this batch was restored since: a
    chunk posted again must not take it out twice.
    """
    with transaction.atomic():
        row = _locked(platform)
        if row.removed_at is not None or row.removed_in_batch == batch:
            return False
        remove(row, batch=batch)
        return True


def restore_platform_from_batch(platform: Platform, *, batch: uuid.UUID) -> Moved:
    """Put back a row this batch removed.

    A row another act removed since stays removed, and says so.
    """
    with transaction.atomic():
        row = _locked(platform)
        if row.removed_at is None:
            return False
        if row.removed_in_batch != batch:
            raise CommandFailed(removed_again_sentence(row), CONFLICT_STATUS)
        _restore(row)
        return True


def restore_platform_by_hand(platform: Platform) -> None:
    """The per-row Undo, refusing a taken name."""
    with transaction.atomic():
        row = _locked(platform)
        if row.removed_at is None:
            return
        _restore(row)
