"""Command idempotency: what a key already produced, and whether the input
behind it is still the same one.

A command names itself with a key. Repeating that key returns the sequence range
the first attempt was given rather than appending a second time; repeating it
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
    NewEvent,
    SourceMetadata,
    lock_stream,
)
from games.models import LibraryIdempotencyRecord, UserLibrary
from timetracker.temporal import TemporalValue

type IdempotencyKey = str  # "session-create-01J8Z3K4M5N6P7Q8R9S0T1U2V3"
type RequestFingerprint = str  # "9f86d081884c7d65..." (sha256 hex)

#: Stamped on every record. Bump it when _encode_command_value or the canonical
#: form changes: records written under another version are no longer comparable
#: and replay unchecked, rather than rejecting every retry that predates it.
FINGERPRINT_VERSION = 1


class IdempotencyKeyMismatch(Exception):
    """Raised when a key already belongs to a command with different input.

    Not a ValueError: `LockedStream.append` raises that for an empty event
    sequence, and #663 must turn a conflict into a visible retry prompt while
    letting that programming error surface as the bug it is.
    """


@dataclass(frozen=True, slots=True)
class ReplayedAppend:
    """A command that already ran. It carries no events, so re-running
    projections against a replay is a type error rather than a review catch."""

    stream_id: uuid.UUID
    first_sequence: int
    last_sequence: int


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


def idempotent_append(
    library: UserLibrary,
    *,
    idempotency_key: IdempotencyKey,
    command_input: dict[str, Any],
    build: Callable[[LockedStream], Sequence[NewEvent]],
    actor: User | None,
    correlation_id: uuid.UUID,
    source_metadata: SourceMetadata | None = None,
    recorded_at: datetime | None = None,
) -> AppendResult | ReplayedAppend:
    """Append the events `build` describes, unless `idempotency_key` already
    produced some -- in which case return the range it produced.

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
        return ReplayedAppend(
            stream_id=stream.stream_id,
            first_sequence=record.first_sequence,
            last_sequence=record.last_sequence,
        )

    result = stream.append(
        build(stream),
        actor=actor,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        source_metadata=source_metadata,
        recorded_at=recorded_at,
    )
    LibraryIdempotencyRecord.objects.create(
        library=library,
        idempotency_key=idempotency_key,
        request_fingerprint=fingerprint,
        fingerprint_version=FINGERPRINT_VERSION,
        first_sequence=result.first_sequence,
        last_sequence=result.last_sequence,
    )
    return result
