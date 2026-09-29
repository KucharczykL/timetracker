"""Entry writes; refusals become answers."""

import uuid
from typing import NamedTuple

from django.contrib.auth.models import User

from games.commands.endpoint import ActStatement
from games.commands.libraryentry import (
    CorrectEntryAcquisition,
    DescribeEntry,
    RecordEntry,
    RemoveEntry,
    RestoreEntry,
)
from games.events.append import SourceMetadata
from games.events.dispatch import Command, CommandOutcome, CommandResult, dispatch
from games.events.idempotency import IdempotencyKey
from games.events.libraryentry import LIBRARYENTRY_CREATED
from games.events.playergame import PLAYERGAME_CREATED
from games.models import LibraryEntry
from games.reads.events import dispatched_events
from games.writes.answers import SubjectNoun, answered

SUBJECT: SubjectNoun = "entry"


class EntryDraft(NamedTuple):
    """What a creation states."""

    release_id: uuid.UUID
    access: str
    format: str
    note: str
    acquired: ActStatement


class RecordedEntry(NamedTuple):
    """What a creation answers."""

    entry_id: uuid.UUID
    #: The dispatch tracked an untracked game.
    tracked_the_game: bool


def _dispatch(
    command: Command,
    *,
    actor: User,
    correlation_id: uuid.UUID,
    idempotency_key: IdempotencyKey | None = None,
    source_metadata: SourceMetadata | None = None,
) -> CommandResult:
    return dispatch(
        command,
        actor=actor,
        library=actor.library,
        #: Caller's key else fresh; blank refused.
        idempotency_key=(
            str(uuid.uuid7()) if idempotency_key is None else idempotency_key
        ),
        correlation_id=correlation_id,
        source_metadata=source_metadata,
    )


def record_entry(
    actor: User,
    draft: EntryDraft,
    *,
    correlation_id: uuid.UUID,
    idempotency_key: IdempotencyKey | None = None,
    source_metadata: SourceMetadata | None = None,
) -> RecordedEntry:
    """State a copy; answer id and tracking."""
    with answered(SUBJECT):
        result = _dispatch(
            RecordEntry(
                release_id=draft.release_id,
                access=draft.access,
                format=draft.format,
                note=draft.note,
                acquired=draft.acquired,
            ),
            actor=actor,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            source_metadata=source_metadata,
        )
    id_by_type = {
        event.event_type: event.aggregate_id for event in dispatched_events(result)
    }
    return RecordedEntry(
        entry_id=id_by_type[LIBRARYENTRY_CREATED.event_type],
        tracked_the_game=PLAYERGAME_CREATED.event_type in id_by_type,
    )


def restate_entry(
    actor: User,
    entry: LibraryEntry,
    *,
    access: str | None = None,
    format: str | None = None,
    note: str | None = None,
    release_id: uuid.UUID | None = None,
    acquired: ActStatement | None = None,
    correlation_id: uuid.UUID,
) -> bool:
    """Describe, then correct the day; one correlation.

    The description goes first: its refusals include every
    one the correction can raise, so a refused body leaves
    the day unmoved. Answers whether anything was appended.
    """
    commands: list[Command] = []
    if any(fact is not None for fact in (access, format, note, release_id)):
        commands.append(
            DescribeEntry(
                entry_id=entry.pk,
                access=access,
                format=format,
                note=note,
                release_id=release_id,
            )
        )
    if acquired is not None:
        commands.append(CorrectEntryAcquisition(entry_id=entry.pk, statement=acquired))
    changed = False
    for command in commands:
        with answered(SUBJECT):
            result = _dispatch(command, actor=actor, correlation_id=correlation_id)
        changed = changed or result.outcome is CommandOutcome.APPENDED
    return changed


def remove_entry(
    actor: User,
    entry: LibraryEntry,
    *,
    correlation_id: uuid.UUID,
    idempotency_key: IdempotencyKey | None = None,
    source_metadata: SourceMetadata | None = None,
) -> CommandResult:
    """Take a copy out of the library."""
    with answered(SUBJECT):
        return _dispatch(
            RemoveEntry(entry_id=entry.pk),
            actor=actor,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            source_metadata=source_metadata,
        )


def restore_entry(
    actor: User,
    entry: LibraryEntry,
    *,
    correlation_id: uuid.UUID,
    idempotency_key: IdempotencyKey | None = None,
    source_metadata: SourceMetadata | None = None,
) -> CommandResult:
    """Put a removed copy back."""
    with answered(SUBJECT):
        return _dispatch(
            RestoreEntry(entry_id=entry.pk),
            actor=actor,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            source_metadata=source_metadata,
        )
