"""Folding a stream that already exists back through the projectors.

The read counterpart of `append`, and the only other place the fold loop is
written: one `registry.apply` per `RecordedEvent`, in sequence order. The two
paths differ in where the row came from and in nothing else, which is what makes
a rebuilt projection equal to the one the write path produced.

The stream head is read first and its sequence bounds the read. Events are
immutable and append-only, so that bound is a consistent snapshot without a lock,
without a transaction, and without repeatable-read isolation: an append that
lands while the fold is running sits above the bound and belongs to a later
replay. `ReplayResult.folded_through` carries the bound out, so a caller that
needs to know whether anything landed can ask the head again itself.

Nothing here empties anything. Replaying onto a projection that already holds
rows folds every event a second time, which is the caller's to prevent.
"""

import uuid
from collections.abc import Generator
from contextlib import closing
from dataclasses import dataclass
from typing import cast

from games.events.envelope import RecordedEvent
from games.events.wiring import DEFAULT_WIRING, EventWiring
from games.models import LibraryEvent, LibraryEventStreamHead, UserLibrary

#: Chunk size is a memory decision rather than a speed one: 500 and 10000 fold
#: 100k events within 2% of each other, at 1 MB against 22 MB.
REPLAY_CHUNK_SIZE = 500


class StreamNotContiguous(Exception):
    """A stream missing a sequence, or ending before its head says it does.

    Deliberately neither an `IntegrityError` nor an `OperationalError`: those are
    what a caller catches to mean "the database was busy", and a stream with a
    hole in it is not a thing another attempt fixes.
    """


@dataclass(frozen=True, slots=True)
class ReplayResult:
    """Which prefix of which stream was folded.

    There is no event count: the contiguity contract makes the sequences exactly
    `1..folded_through`, so a count could only ever agree with it.
    """

    #: None when the library has never appended: an empty stream, not an error.
    stream_id: uuid.UUID | None
    folded_through: int


def replay(
    library: UserLibrary, *, wiring: EventWiring = DEFAULT_WIRING
) -> ReplayResult:
    """Fold `library`'s recorded events through `wiring.projectors`, oldest
    first."""
    head = LibraryEventStreamHead.objects.filter(library=library).first()
    if head is None:
        #: Never appended. A read that provisions its own head is a read nobody
        #: can run safely.
        return ReplayResult(stream_id=None, folded_through=0)

    bound = head.current_sequence
    #: Filtering on the stream alone scopes the read to one library: a composite
    #: foreign key ties an event's stream and library together in the database.
    #: The cast covers `iterator`, typed as returning a plain iterator while
    #: returning a generator, whose `close` releases the cursor below.
    rows = cast(
        Generator[LibraryEvent],
        LibraryEvent.objects.filter(stream_id=head.id, sequence__lte=bound)
        .order_by("sequence")
        .iterator(chunk_size=REPLAY_CHUNK_SIZE),
    )

    previous = 0
    #: Closed explicitly: in autocommit the server-side cursor is declared WITH
    #: HOLD, and a refusal below abandons the generator while the traceback keeps
    #: its frame alive.
    with closing(rows):
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
            wiring.projectors.apply(event)

    if previous != bound:
        raise StreamNotContiguous(
            f"This stream ends at {previous}, but its head records {bound}. "
            "The events above the last one folded are missing."
        )
    return ReplayResult(stream_id=head.id, folded_through=bound)
