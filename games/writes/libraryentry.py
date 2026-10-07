"""Entry writes; refusals become answers."""

import uuid
from typing import NamedTuple, assert_never

from django.contrib.auth.models import User

from games.commands.endpoint import ActStatement, WayActStatement, certainly_reversed
from games.commands.libraryentry import (
    ACQUISITION_AFTER_END,
    END_BEFORE_ACQUISITION,
    CorrectEntryAccessEnd,
    CorrectEntryAcquisition,
    DescribeEntry,
    EndEntryAccess,
    EntryStatement,
    RecordEntry,
    RemoveEntry,
    RestoreEntry,
    ResumeEntryAccess,
    UndoEntryAccessEnd,
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
from games.models import EntryAccess, EntryFormat, LibraryEntry
from games.reads.endpoints import stated
from games.reads.events import dispatched_events
from games.writes.answers import SubjectNoun, answered
from games.writes.endpoint import (
    KEEP,
    Act,
    Correct,
    Keep,
    Nothing,
    Restated,
    Void,
    endpoint_move,
)
from games.writes.revaluation import appended_types, revalue_after

SUBJECT: SubjectNoun = "copy"


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
    draft: EntryStatement,
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
    access: EntryAccess | None = None,
    format: EntryFormat | None = None,
    note: str | None = None,
    release_id: uuid.UUID | None = None,
    acquired: ActStatement | Keep = KEEP,
    access_end: Restated[WayActStatement] = KEEP,
    correlation_id: uuid.UUID,
) -> bool:
    """Describe, then move both endpoints; one correlation.

    A reversed day order is refused before any dispatch; the
    description then carries every live-act refusal, so a
    refused body appends nothing. Answers whether anything
    was appended.
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


def describe_entry(
    actor: User,
    entry: LibraryEntry,
    *,
    access: EntryAccess | None = None,
    format: EntryFormat | None = None,
    note: str | None = None,
    release_id: uuid.UUID | None = None,
    correlation_id: uuid.UUID,
    idempotency_key: IdempotencyKey | None = None,
    source_metadata: SourceMetadata | None = None,
) -> CommandResult:
    """One description; None states nothing."""
    with answered(SUBJECT):
        return _dispatch(
            DescribeEntry(
                entry_id=entry.pk,
                access=access,
                format=format,
                note=note,
                release_id=release_id,
            ),
            actor=actor,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            source_metadata=source_metadata,
        )


def _refuse_a_reversed_draft(
    entry: LibraryEntry,
    *,
    acquired: ActStatement | Keep,
    access_end: Restated[WayActStatement],
) -> None:
    """Refuse up front: a committed act stays.

    Each stated day is compared with the other one the row
    keeps, so a refusal a command would raise later is raised
    before the description commits.
    """
    match access_end:
        case WayActStatement():
            ended, end_is_new = access_end.when, True
        case Keep() if stated(entry, ENTRY_ACCESS_END) is not None:
            ended, end_is_new = entry.access_ended, False
        case _:
            return
    if isinstance(acquired, Keep):
        acquired_day, acquisition_is_new = entry.acquired, False
    else:
        acquired_day, acquisition_is_new = acquired.when, True
    if not (end_is_new or acquisition_is_new):
        return
    if not certainly_reversed(earlier=acquired_day, later=ended):
        return
    if end_is_new and acquisition_is_new:
        sentence = "This copy left before it was acquired. Check the days."
    elif end_is_new:
        sentence = END_BEFORE_ACQUISITION
    else:
        sentence = ACQUISITION_AFTER_END
    raise CommandRejected(
        f"The statement about entry {entry.pk} ends its access before it was acquired.",
        sentence=sentence,
    )


def _endpoint_commands(
    entry: LibraryEntry,
    *,
    acquired: ActStatement | Keep,
    access_end: Restated[WayActStatement],
) -> list[Command]:
    """Both endpoints, in the order that never reverses them.

    One is stated at a time, so in between the row holds one
    new day beside one old one. The end goes first unless its
    new day certainly falls before the acquisition the row
    holds.
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
) -> Command:
    """The act; a void always dispatches.

    The command decides under the lock, so an end a racer
    stated is voided rather than dropped.
    """
    match endpoint_move(stated(entry, ENTRY_ACCESS_END), access_end):
        case Act(statement):
            return EndEntryAccess(entry_id=entry.pk, statement=statement)
        case Correct(statement):
            return CorrectEntryAccessEnd(entry_id=entry.pk, statement=statement)
        case Void() | Nothing():
            return VoidEntryAccessEnd(entry_id=entry.pk)
        case unhandled:
            assert_never(unhandled)


def end_entry_access(
    actor: User,
    entry: LibraryEntry,
    statement: WayActStatement,
    *,
    correlation_id: uuid.UUID,
    idempotency_key: IdempotencyKey | None = None,
    source_metadata: SourceMetadata | None = None,
) -> CommandResult:
    """Access to a held copy ended."""
    with answered(SUBJECT):
        return _dispatch(
            EndEntryAccess(entry_id=entry.pk, statement=statement),
            actor=actor,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            source_metadata=source_metadata,
        )


def undo_entry_access_end(
    actor: User,
    entry: LibraryEntry,
    *,
    batch_id: uuid.UUID,
    correlation_id: uuid.UUID,
    idempotency_key: IdempotencyKey | None = None,
    source_metadata: SourceMetadata | None = None,
) -> CommandResult:
    """Void a batch's end, still latest."""
    with answered(SUBJECT):
        return _dispatch(
            UndoEntryAccessEnd(entry_id=entry.pk, batch_id=batch_id),
            actor=actor,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            source_metadata=source_metadata,
        )


def resume_entry_access(
    actor: User,
    entry: LibraryEntry,
    statement: ActStatement,
    *,
    correlation_id: uuid.UUID,
    idempotency_key: IdempotencyKey | None = None,
) -> CommandResult:
    """Access to an ended copy resumed."""
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
        result = _dispatch(
            RestoreEntry(entry_id=entry.pk),
            actor=actor,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            source_metadata=source_metadata,
        )
    #: Its purchases may come back too.
    revalue_after(actor, appended_types(result))
    return result
