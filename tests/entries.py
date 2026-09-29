"""Test entries via append_command; dispatch cannot nest."""

import uuid

from django.db import transaction

from games.commands.endpoint import ActStatement
from games.commands.libraryentry import RecordEntry, RemoveEntry, RestoreEntry
from games.events.dispatch import Command, CommandResult, append_command
from games.models import LibraryEntry, LibraryEvent, Release, UserLibrary
from timetracker.temporal import TemporalValue


def _state(library: UserLibrary, command: Command) -> CommandResult:
    with transaction.atomic():
        return append_command(
            command,
            actor=library.user,
            library=library,
            idempotency_key=str(uuid.uuid7()),
            correlation_id=uuid.uuid7(),
        )


def record_entry(
    library: UserLibrary,
    release: Release,
    *,
    access: str = "owned",
    format: str = "digital",
    note: str = "",
    acquired: TemporalValue | None = None,
    acquisition_note: str = "",
) -> LibraryEntry:
    """A live entry by event; tracks the game."""
    result = _state(
        library,
        RecordEntry(
            release_id=release.pk,
            access=access,
            format=format,
            note=note,
            acquired=ActStatement(acquired, acquisition_note),
        ),
    )
    assert result.sequences is not None
    #: The creation is the dispatch's last event.
    created = LibraryEvent.objects.get(
        stream_id=result.stream_id, sequence=result.sequences.last
    )
    return LibraryEntry.objects.get(pk=created.aggregate_id)


def remove_entry(entry: LibraryEntry) -> LibraryEntry:
    _state(entry.library, RemoveEntry(entry_id=entry.pk))
    entry.refresh_from_db()
    return entry


def restore_entry(entry: LibraryEntry) -> LibraryEntry:
    _state(entry.library, RestoreEntry(entry_id=entry.pk))
    entry.refresh_from_db()
    return entry
