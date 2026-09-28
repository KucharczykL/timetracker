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


def taken_sentence(platform: Platform) -> str:
    """Why this platform cannot come back."""
    named = f"{platform.name} ({platform.group})" if platform.group else platform.name
    return (
        f"{named} cannot come back: another platform with that name is in "
        "your library now. Rename or remove that one first."
    )


def _refuse_a_taken_name(platform: Platform) -> None:
    """A live platform, private or shared, holding its name.

    The unique constraints cover private beside private only;
    `Platform.clean()` refuses shadowing a shared one, and a stamp
    calls no `clean()`.
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


def _restore(platform: Platform) -> None:
    """Put it back, or refuse with a sentence."""
    _refuse_a_taken_name(platform)
    try:
        #: A savepoint: the batch continues.
        with transaction.atomic():
            restore(platform)
    except IntegrityError as collision:
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
    """Put back a row this batch removed."""
    with transaction.atomic():
        row = _locked(platform)
        if row.removed_at is None or row.removed_in_batch != batch:
            return False
        _restore(row)
        return True


def restore_platform_by_hand(platform: Platform) -> None:
    """The per-row Undo, refusing a taken name."""
    with transaction.atomic():
        row = _locked(platform)
        if row.removed_at is None:
            return
        _restore(row)
