"""A platform removed, edited and restored, locked first.

A platform writes no event, so every batch write records the value
before it in the batch ledger, in the same transaction.
"""

import uuid

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.db.models.functions import Lower, Trim

from common.naming import name_key
from games.batch_ledger import ActName, FieldName, record, recorded, row_changes
from games.bulk_edit import log_overwrite
from games.models import Platform, UserLibrary
from games.removal import remove, restore
from games.writes.answers import CONFLICT_STATUS, CommandFailed

#: Whether the write changed the row.
type Moved = bool

REMOVED_AT: FieldName = "removed_at"
GROUP: FieldName = "group"
ICON: FieldName = "icon"

#: The constraints answered as a taken name.
NAME_CONSTRAINTS = frozenset(
    {
        "unique_private_platform_normalized_name_group",
        "unique_shared_platform_normalized_name_group",
    }
)

PLATFORM_REMOVED = "That platform is removed. Restore it first."


def taken_sentence(platform: Platform) -> str:
    """Why this platform cannot come back."""
    return (
        f"{platform.named_with_group} cannot come back: another platform "
        "with that name is in your library now. Rename or remove that one "
        "first."
    )


def group_taken_sentence(platform: Platform, group: str) -> str:
    """Why this platform cannot take that group."""
    named = f"{platform.name} ({group})" if group else platform.name
    return (
        f"{platform.named_with_group} cannot become {named}: another "
        "platform in your library is named so. Rename or remove that one "
        "first."
    )


def _name_is_taken(platform: Platform, group: str) -> bool:
    """A live platform, private or shared, holding name and group.

    The constraints compare private with private and shared with
    shared; `clean()` refuses a private row shadowing a shared one,
    and neither a stamp nor `update()` calls `clean()`.
    """
    return (
        Platform.objects.alive()
        .exclude(pk=platform.pk)
        .filter(Q(library__isnull=True) | Q(library=platform.library_id))
        .annotate(
            normalized_name=Lower(Trim("name")),
            normalized_group=Lower(Trim("group")),
        )
        .filter(
            normalized_name=name_key(platform.name),
            normalized_group=name_key(group),
        )
        .exists()
    )


def _constraint_of(collision: IntegrityError) -> str | None:
    diagnostic = getattr(collision.__cause__, "diag", None)
    return None if diagnostic is None else diagnostic.constraint_name


def _refusing_a_taken_name(write, sentence: str) -> None:
    """Run the write; a name constraint is a taken name.

    Such a constraint is an insert racing the check; any other rises
    as itself, a defect.
    """
    try:
        write()
    except IntegrityError as collision:
        if _constraint_of(collision) not in NAME_CONSTRAINTS:
            raise
        raise CommandFailed(sentence, CONFLICT_STATUS) from collision


def _restore(platform: Platform) -> None:
    """Put it back, or refuse with a sentence."""
    if _name_is_taken(platform, platform.group):
        raise CommandFailed(taken_sentence(platform), CONFLICT_STATUS)
    _refusing_a_taken_name(lambda: restore(platform), taken_sentence(platform))


def _state_fields(platform: Platform, stated: dict[FieldName, str]) -> None:
    """Write group and icon, refusing a taken name."""
    group = stated.get(GROUP)
    sentence = group_taken_sentence(
        platform, platform.group if group is None else group
    )
    if group is not None and _name_is_taken(platform, group):
        raise CommandFailed(sentence, CONFLICT_STATUS)
    _refusing_a_taken_name(
        lambda: Platform.objects.filter(pk=platform.pk).update(**stated), sentence
    )
    for field, value in stated.items():
        setattr(platform, field, value)


def _locked(platform: Platform) -> tuple[Platform, UserLibrary]:
    """The row, locked, and the library holding it."""
    row = Platform.objects.select_for_update().get(pk=platform.pk)
    if row.library is None:
        raise ValueError(f"Platform {row.pk} is shared: no batch writes it.")
    return row, row.library


def remove_platform_in_batch(
    platform: Platform, *, batch: uuid.UUID, act: ActName
) -> Moved:
    """Take a live row out, recording it.

    A live row this batch already removed was restored since: a
    chunk posted again must not take it out twice.
    """
    with transaction.atomic():
        row, library = _locked(platform)
        if row.removed_at is not None or recorded(
            library, batch=batch, row=row, field=REMOVED_AT
        ):
            return False
        remove(row)
        record(
            library,
            batch=batch,
            act=act,
            row=row,
            field=REMOVED_AT,
            earlier=None,
            stated=row.removed_at,
        )
        return True


def edit_platform_in_batch(
    platform: Platform,
    *,
    group: str | None,
    icon: str | None,
    batch: uuid.UUID,
    act: ActName,
) -> Moved:
    """State group and icon; None keeps.

    A field this batch already wrote is not written again.
    """
    with transaction.atomic():
        row, library = _locked(platform)
        wanted = {
            field: value
            for field, value in ((GROUP, group), (ICON, icon))
            if value is not None
            and value != getattr(row, field)
            and not recorded(library, batch=batch, row=row, field=field)
        }
        if not wanted:
            return False
        earlier = {field: getattr(row, field) for field in wanted}
        _state_fields(row, wanted)
        for field, value in wanted.items():
            record(
                library,
                batch=batch,
                act=act,
                row=row,
                field=field,
                earlier=earlier[field],
                stated=value,
            )
        return True


def undo_platform_batch(
    platform: Platform, *, undoes: uuid.UUID, batch: uuid.UUID, act: ActName
) -> Moved:
    """Write back what one batch changed, over a later change too.

    Records its own writes, so a chunk posted again skips them.
    """
    with transaction.atomic():
        row, library = _locked(platform)
        restating = {
            field: change
            for field, change in row_changes(library, undoes, row).items()
            if not recorded(library, batch=batch, row=row, field=field)
            and getattr(row, field) != change.before
        }
        if not restating:
            return False
        fields = {field: str(change.before) for field, change in restating.items()}
        fields.pop(REMOVED_AT, None)
        if fields and row.removed_at is not None and REMOVED_AT not in restating:
            raise CommandFailed(PLATFORM_REMOVED, CONFLICT_STATUS)
        held = {field: getattr(row, field) for field in restating}
        if REMOVED_AT in restating:
            _restore(row)
        if fields:
            _state_fields(row, fields)
        for field, change in restating.items():
            log_overwrite(
                change,
                held[field],
                act_name=act,
                fact=field,
                row_description=f"platform {row.pk} of library {library.pk}",
            )
            record(
                library,
                batch=batch,
                act=f"{act}.undo",
                row=row,
                field=field,
                earlier=held[field],
                stated=change.before,
            )
        return True


def restore_platform_by_hand(platform: Platform) -> None:
    """The per-row Undo, refusing a taken name."""
    with transaction.atomic():
        row, _ = _locked(platform)
        if row.removed_at is None:
            return
        _restore(row)
