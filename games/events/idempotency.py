"""Command idempotency: what a key already produced, and whether the input
behind it is still the same one.

A command names itself with a key. Repeating that key answers from what the
first attempt did rather than appending a second time: the sequence range it was
given, or, for a command that changed nothing, no range at all. Repeating a key
over different input is refused.
"""

import hashlib
import json
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from django.contrib.auth.models import User

from games.events.append import (
    AppendResult,
    LockedStream,
    SourceMetadata,
    lock_stream,
)
from games.events.conflicts import CommandConflict
from games.events.vocabulary import NewEvent, Unchanged
from games.events.wiring import DEFAULT_WIRING, EventWiring
from games.models import LibraryIdempotencyRecord, UserLibrary
from timetracker.temporal import TemporalValue

type IdempotencyKey = str  # "session-create-01J8Z3K4M5N6P7Q8R9S0T1U2V3"
type RequestFingerprint = str  # "9f86d081884c7d65..." (sha256 hex)

#: Stamped on every record. Bump it when _encode_command_value or the canonical
#: form changes: records written under another version are no longer comparable
#: and replay unchecked, rather than rejecting every retry that predates it.
FINGERPRINT_VERSION = 1


class IdempotencyKeyMismatch(CommandConflict):
    """Raised when a key already belongs to a command with different input.

    Not a ValueError: `LockedStream.append` raises that for an empty event
    sequence, and a conflict must become a visible retry prompt while letting
    that programming error surface as the bug it is.
    """


@dataclass(frozen=True, slots=True)
class ReplayedAppend:
    """A command that already ran. It carries no events, so re-running
    projections against a replay is a type error rather than a review catch."""

    stream_id: uuid.UUID
    first_sequence: int
    last_sequence: int


@dataclass(frozen=True, slots=True)
class UnchangedAppend:
    """A command that found its work already done. It carries no range, because
    it appended nothing, and no events for the same reason."""

    stream_id: uuid.UUID
    #: None when a claimed key answered, so no build ran to explain itself.
    reason: str | None


def _encode_command_value(value: Any) -> str | None:
    #: datetime before date -- datetime subclasses date, so the reverse order
    #: would silently reduce every timestamp to its calendar day.
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, TemporalValue):
        #: None for an unknown time, which json renders as null.
        return value.canonical
    raise TypeError(
        f"{type(value).__name__} has no canonical form for an idempotency "
        "fingerprint. Convert it at the call site: a repr() fallback would "
        "vary between processes and turn honest retries into mismatches."
    )


def fingerprint_command_input(command_input: dict[str, Any]) -> RequestFingerprint:
    """Hash a command's canonical input, so a key reused over different input
    can be told from an honest retry.

    The parameter is `dict`, not `Mapping`: json's encoder dispatches on
    `isinstance(o, dict)`, so any other Mapping reaches `default` and raises.
    """
    canonical = json.dumps(
        command_input,
        sort_keys=True,
        separators=(",", ":"),
        default=_encode_command_value,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _record_range(
    library: UserLibrary,
    *,
    idempotency_key: IdempotencyKey,
    fingerprint: RequestFingerprint,
    first_sequence: int | None,
    last_sequence: int | None,
) -> None:
    """Claim the key. Both sequences, or neither: a command that changed
    nothing claims its key just as firmly as one that appended."""
    LibraryIdempotencyRecord.objects.create(
        library=library,
        idempotency_key=idempotency_key,
        request_fingerprint=fingerprint,
        fingerprint_version=FINGERPRINT_VERSION,
        first_sequence=first_sequence,
        last_sequence=last_sequence,
    )


def idempotent_append(
    library: UserLibrary,
    *,
    idempotency_key: IdempotencyKey,
    command_input: dict[str, Any],
    build: Callable[[LockedStream], Sequence[NewEvent] | Unchanged],
    actor: User | None,
    correlation_id: uuid.UUID,
    source_metadata: SourceMetadata | None = None,
    recorded_at: datetime | None = None,
    wiring: EventWiring = DEFAULT_WIRING,
) -> AppendResult | ReplayedAppend | UnchangedAppend:
    """Append the events `build` describes, unless `idempotency_key` already
    answered -- in which case return what it produced: the range of the append,
    or no range at all where the command changed nothing.

    `build` runs under the stream-head lock, after the key has been checked, so
    a command validates against projections that cannot move and a duplicate
    does no validation work at all.

    The input is hashed here rather than accepted as a digest: a fingerprint
    parameter is an ordinary string, so a caller passing a constant would
    silently disable mismatch rejection.
    """
    fingerprint = fingerprint_command_input(command_input)
    stream = lock_stream(library)
    record = LibraryIdempotencyRecord.objects.filter(
        library=library, idempotency_key=idempotency_key
    ).first()

    if record is not None:
        #: A digest from another canonicalizer cannot be compared, so the key
        #: replays unchecked: idempotency outlives a version bump, and only the
        #: mismatch guard lapses for keys predating it.
        if (
            record.fingerprint_version == FINGERPRINT_VERSION
            and record.request_fingerprint != fingerprint
        ):
            raise IdempotencyKeyMismatch(
                f"Idempotency key {idempotency_key!r} already recorded a "
                f"different command for library {library.pk}."
            )
        #: The constraint takes both columns or neither; testing both is what
        #: narrows the pair for the type checker.
        if record.first_sequence is None or record.last_sequence is None:
            return UnchangedAppend(stream_id=stream.stream_id, reason=None)
        return ReplayedAppend(
            stream_id=stream.stream_id,
            first_sequence=record.first_sequence,
            last_sequence=record.last_sequence,
        )

    built = build(stream)
    if isinstance(built, Unchanged):
        #: Claimed, so a repeat of this request cannot append once another
        #: writer has moved the state out from under it.
        _record_range(
            library,
            idempotency_key=idempotency_key,
            fingerprint=fingerprint,
            first_sequence=None,
            last_sequence=None,
        )
        return UnchangedAppend(stream_id=stream.stream_id, reason=built.reason)

    result = stream.append(
        built,
        actor=actor,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        source_metadata=source_metadata,
        recorded_at=recorded_at,
        wiring=wiring,
    )
    _record_range(
        library,
        idempotency_key=idempotency_key,
        fingerprint=fingerprint,
        first_sequence=result.first_sequence,
        last_sequence=result.last_sequence,
    )
    return result
