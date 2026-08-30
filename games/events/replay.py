"""Replaying a stream that already exists back through the projectors.

The read counterpart of `append`, and the only other place the replay loop is
written: one `registry.apply` per `RecordedEvent`, in sequence order. The two
paths differ in where the row came from and in nothing else, which is what makes
a rebuilt projection equal to the one the write path produced.

The stream head is read first and its sequence bounds the read. Events are
immutable and append-only, so that bound is a consistent snapshot without a lock,
without a transaction, and without repeatable-read isolation: an append that
lands while the replay is running sits above the bound and belongs to a later
replay. `ReplayResult.replayed_through` carries the bound out, so a caller that
needs to know whether anything landed can ask the head again itself.

A row the wired vocabulary cannot read -- an unregistered event type, or a
payload recorded against another schema version -- refuses the whole replay rather
than being skipped: a projection built from whichever events happened to be
readable is not the one the append path produced.

A stream whose REQUIRED references name rows that no longer exist is refused for
the same reason, and before the first row is read.

Nothing here empties anything. Replaying onto a projection that already holds
rows replays every event a second time, which is the caller's to prevent.
"""

import uuid
from dataclasses import dataclass

from common.keyset import keyset_pages
from games.events.envelope import RecordedEvent
from games.events.reconcile import require_resolvable_references
from games.events.vocabulary import EventTypeRegistry
from games.events.wiring import DEFAULT_WIRING, EventWiring
from games.models import LibraryEvent, LibraryEventStreamHead, UserLibrary

#: Page size is a memory decision rather than a speed one: 500 and 10000 replay
#: 100k events within 2% of each other, at 1 MB against 22 MB.
REPLAY_CHUNK_SIZE = 500


class StreamNotContiguous(Exception):
    """A stream missing a sequence, or ending before its head says it does.

    Deliberately neither an `IntegrityError` nor an `OperationalError`: those are
    what a caller catches to mean "the database was busy", and a stream with a
    hole in it is not a thing another attempt fixes.
    """


class PayloadVersionUnsupported(Exception):
    """A payload no registered schema can read."""


@dataclass(frozen=True, slots=True)
class ReplayResult:
    """Which prefix of which stream was replayed.

    There is no event count: the contiguity contract makes the sequences exactly
    `1..replayed_through`, so a count could only ever agree with it.
    """

    #: None when the library has never appended: an empty stream, not an error.
    stream_id: uuid.UUID | None
    replayed_through: int


def replay(
    library: UserLibrary, *, wiring: EventWiring = DEFAULT_WIRING
) -> ReplayResult:
    """Replay a library's recorded events, oldest first."""
    head = LibraryEventStreamHead.objects.filter(library=library).first()
    if head is None:
        #: Never appended. A read that provisions its own head is a read nobody
        #: can run safely.
        return ReplayResult(stream_id=None, replayed_through=0)

    #: One report, ahead of the whole replay.
    require_resolvable_references(library, kinds=wiring.event_types.reference_kinds)

    bound = head.current_sequence
    #: Filtering on the stream alone scopes the read to one library: a composite
    #: foreign key ties an event's stream and library together in the database.
    #: Keyed on sequence, which a constraint indexes.
    rows = keyset_pages(
        LibraryEvent.objects.filter(stream_id=head.id, sequence__lte=bound),
        key=("sequence",),
        page_size=REPLAY_CHUNK_SIZE,
    )

    previous = 0
    for row in rows:
        event = RecordedEvent.from_row(row)
        if event.sequence != previous + 1:
            raise StreamNotContiguous(
                f"This stream records no event #{previous + 1}: sequence "
                f"{event.sequence} follows {previous}. Every sequence from 1 "
                f"to {bound} must be present for a replay to reach the state "
                "the append path did."
            )
        previous = event.sequence
        _check_readable(event, wiring.event_types)
        wiring.projectors.apply(event)

    if previous != bound:
        raise StreamNotContiguous(
            f"This stream ends at {previous}, but its head records {bound}. "
            "The events above the last one replayed are missing."
        )
    return ReplayResult(stream_id=head.id, replayed_through=bound)


def _check_readable(event: RecordedEvent, event_types: EventTypeRegistry) -> None:
    """Refuse what the vocabulary cannot read."""
    spec = event_types.spec_for(event.event_type)
    if event.payload_schema_version != spec.version:
        raise PayloadVersionUnsupported(
            f"Event #{event.sequence} records a {event.event_type} payload at "
            f"schema version {event.payload_schema_version}, but the vocabulary "
            f"holds version {spec.version}. Nothing upcasts a recorded payload "
            "to another schema yet, so this stream cannot be replayed."
        )
