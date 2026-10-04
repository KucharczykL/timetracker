"""Access to many copies ends at once."""

import uuid
from collections.abc import Sequence
from functools import partial

from django.contrib.auth.models import User

from common.temporal_presentation import present_temporal_value
from games.bulk_access_end import access_end_choice, decode_access_end
from games.bulk_actions import BulkAction
from games.bulk_edit import settled
from games.bulk_endpoint_undo import UndoSentences, refuse_unless_this_batch_wrote_it
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
from games.events.libraryentry import ENTRY_ACCESS_END_EVENTS
from games.models import ENTRY_WAYS, LibraryEntry
from games.reads.entries import copy_end
from games.reads.events import aggregate_events
from games.writes.answers import answered
from games.writes.libraryentry import (
    SUBJECT,
    end_entry_access,
    void_entry_access_end,
)

ENDED_ONE = "One of these copies has already ended, so it will be left as it is."
ENDED_MANY = (
    "{count} of these copies have already ended, so they will be left as they are."
)

ENTRY_UNDO = UndoSentences(
    not_stated="That copy was not ended by this batch, so it was left as it is.",
    changed_since="That copy has changed since this batch, so it was left as it is.",
)

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
            partial(decode_access_end, ways=ENTRY_WAYS),
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
    """Void the end, where still the batch's."""
    entry = removed_entry(actor, entry_id)
    with answered(SUBJECT):
        refuse_unless_this_batch_wrote_it(
            aggregate_events(actor.library, entry_id),
            ENTRY_ACCESS_END_EVENTS,
            batch_id=undoes,
            row_description=f"LibraryEntry {entry_id} of library {entry.library_id}",
            sentences=ENTRY_UNDO,
        )
    return RowOutcome.of(
        void_entry_access_end(
            actor,
            entry,
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
    choice=access_end_choice(ENTRY_WAYS),
    caution=already_ended,
)
