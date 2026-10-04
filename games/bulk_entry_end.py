"""Access to many copies ends at once."""

import uuid
from collections.abc import Sequence

from django.contrib.auth.models import User

from common.temporal_presentation import present_temporal_value
from games.bulk_access_end import AccessEndQuestion
from games.bulk_actions import BulkAction
from games.bulk_edit import settled
from games.bulk_entries import (
    ENTRY_PREVIEW,
    entry_resolution,
    entry_scope,
    removed_entry,
)
from games.bulk_parts import (
    ActTitle,
    ChoiceValue,
    EventRows,
    Presentations,
    PreviewColumn,
    RowOutcome,
)
from games.events.append import SourceMetadata
from games.events.idempotency import IdempotencyKey
from games.models import ENTRY_WAYS, LibraryEntry
from games.reads.entries import copy_end
from games.writes.answers import answered
from games.writes.libraryentry import (
    SUBJECT,
    end_entry_access,
    undo_entry_access_end,
)

ENDED_ONE = "One of these copies has already ended, so it will be left as it is."
ENDED_MANY = (
    "{count} of these copies have already ended, so they will be left as they are."
)

ENTRY_END_QUESTION = AccessEndQuestion(ENTRY_WAYS)

#: A held copy's Ended cell.
_HELD = "–"


def already_ended(rows: Sequence[LibraryEntry]) -> str | None:
    """Count ended rows; never a note about zero."""
    ended = sum(1 for row in rows if copy_end(row) is not None)
    if not ended:
        return None
    return ENDED_ONE if ended == 1 else ENDED_MANY.format(count=ended)


def _ended(row: LibraryEntry, presentations: Presentations) -> str:
    end = copy_end(row)
    if end is None:
        return _HELD
    return present_temporal_value(end.when, presentations.dates)


END_PREVIEW: tuple[PreviewColumn[LibraryEntry], ...] = (
    *ENTRY_PREVIEW,
    PreviewColumn("Ended", _ended),
)


def _source() -> SourceMetadata:
    return {"bulk": {"action": ENTRY_END.name}}


def end_one(
    actor: User,
    entry: LibraryEntry,
    *,
    choice: ChoiceValue | None,
    idempotency_key: IdempotencyKey,
    correlation_id: uuid.UUID,
) -> RowOutcome:
    with answered(SUBJECT):
        statement = settled(
            choice,
            ENTRY_END_QUESTION.decode,
            act_name=ENTRY_END.name,
            row_description=f"LibraryEntry {entry.pk} of library {actor.library.pk}",
        )
    return RowOutcome.of(
        end_entry_access(
            actor,
            entry,
            statement,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            source_metadata=_source(),
        )
    )


def end_back(
    actor: User,
    entry_id: uuid.UUID,
    *,
    undoes: uuid.UUID,
    idempotency_key: IdempotencyKey,
    correlation_id: uuid.UUID,
) -> RowOutcome:
    """Void the end unless another act wrote it."""
    entry = removed_entry(actor, entry_id)
    return RowOutcome.of(
        undo_entry_access_end(
            actor,
            entry,
            batch_id=undoes,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            source_metadata=_source(),
        )
    )


ENTRY_END = BulkAction(
    name="entry.end",
    label="I no longer have them…",
    title=ActTitle(
        one="I no longer have this copy", many="I no longer have these {count} copies"
    ),
    confirm_label="Save",
    subject=SUBJECT,
    color="blue",
    undo_rows=EventRows(LibraryEntry),
    fallback="games:list_library",
    scope=entry_scope,
    resolve=entry_resolution,
    run=end_one,
    inverse=end_back,
    preview=END_PREVIEW,
    choice=ENTRY_END_QUESTION.choice(),
    caution=already_ended,
)
