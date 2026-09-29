"""Entry writes; refusals become answers."""

import uuid
from enum import Enum
from typing import Final, NamedTuple, assert_never

from django.contrib.auth.models import User

from games.commands.endpoint import ActStatement, WayActStatement, certainly_reversed
from games.commands.libraryentry import (
    CorrectEntryAccessEnd,
    CorrectEntryAcquisition,
    DescribeEntry,
    EndEntryAccess,
    RecordEntry,
    RemoveEntry,
    RestoreEntry,
    ResumeEntryAccess,
    VoidEntryAccessEnd,
)
from games.endpoints import ENTRY_ACCESS_END
from games.events.append import SourceMetadata
from games.events.dispatch import (
    Command,
    CommandOutcome,
    CommandRejected,
    CommandResult,
    dispatch,
)
from games.events.idempotency import IdempotencyKey
from games.events.libraryentry import LIBRARYENTRY_CREATED
from games.events.playergame import PLAYERGAME_CREATED
from games.models import LibraryEntry
from games.reads.endpoints import stated
from games.reads.events import dispatched_events
from games.writes.answers import SubjectNoun, answered
from games.writes.endpoint import Act, Correct, Nothing, Void, endpoint_move

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


class Keep(Enum):
    """No statement; None is a void."""

    KEEP = "keep"


KEEP: Final = Keep.KEEP


def restate_entry(
    actor: User,
    entry: LibraryEntry,
    *,
    access: str | None = None,
    format: str | None = None,
    note: str | None = None,
    release_id: uuid.UUID | None = None,
    acquired: ActStatement | Keep = KEEP,
    access_end: WayActStatement | None | Keep = KEEP,
    correlation_id: uuid.UUID,
) -> bool:
    """Describe, then move both endpoints; one correlation.

    The description goes first: its refusals include every
    live-act one the endpoints raise, so a refused body moves
    no day. Answers whether anything was appended.
    """
    with answered(SUBJECT):
        _refuse_a_reversed_draft(entry, acquired=acquired, access_end=access_end)
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
    commands.extend(_endpoint_commands(entry, acquired=acquired, access_end=access_end))
    changed = False
    for command in commands:
        with answered(SUBJECT):
            result = _dispatch(command, actor=actor, correlation_id=correlation_id)
        changed = changed or result.outcome is CommandOutcome.APPENDED
    return changed


def _refuse_a_reversed_draft(
    entry: LibraryEntry,
    *,
    acquired: ActStatement | Keep,
    access_end: WayActStatement | None | Keep,
) -> None:
    """Refused up front: no act withdraws a committed one."""
    if isinstance(acquired, Keep) or not isinstance(access_end, WayActStatement):
        return
    if certainly_reversed(earlier=acquired.when, later=access_end.when):
        raise CommandRejected(
            f"The statement about entry {entry.pk} ends its access before it "
            "was acquired.",
            sentence="This copy left before it was acquired. Check the days.",
        )


def _endpoint_commands(
    entry: LibraryEntry,
    *,
    acquired: ActStatement | Keep,
    access_end: WayActStatement | None | Keep,
) -> list[Command]:
    """Both endpoints, in the order that never reverses them.

    One is stated at a time, so in between the row holds one
    new day beside one old one. The end goes first unless its
    new day falls before the acquisition the row holds.
    """
    end = (
        None if isinstance(access_end, Keep) else _access_end_command(entry, access_end)
    )
    correction = (
        None
        if isinstance(acquired, Keep)
        else CorrectEntryAcquisition(entry_id=entry.pk, statement=acquired)
    )
    acquisition_first = isinstance(access_end, WayActStatement) and certainly_reversed(
        earlier=entry.acquired, later=access_end.when
    )
    ordered = (correction, end) if acquisition_first else (end, correction)
    return [command for command in ordered if command is not None]


def _access_end_command(
    entry: LibraryEntry, access_end: WayActStatement | None
) -> Command | None:
    match endpoint_move(stated(entry, ENTRY_ACCESS_END), access_end):
        case Act(statement):
            return EndEntryAccess(entry_id=entry.pk, statement=statement)
        case Correct(statement):
            return CorrectEntryAccessEnd(entry_id=entry.pk, statement=statement)
        case Void():
            return VoidEntryAccessEnd(entry_id=entry.pk)
        case Nothing():
            return None
        case unhandled:
            assert_never(unhandled)


def resume_entry_access(
    actor: User,
    entry: LibraryEntry,
    statement: ActStatement,
    *,
    correlation_id: uuid.UUID,
    idempotency_key: IdempotencyKey | None = None,
) -> CommandResult:
    """State that access to an ended copy started again."""
    with answered(SUBJECT):
        return _dispatch(
            ResumeEntryAccess(entry_id=entry.pk, statement=statement),
            actor=actor,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )


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
