"""One event, appended rather than dispatched."""

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from django.contrib.auth.models import User

from games.events.append import AppendResult, LockedStream, SourceMetadata
from games.events.idempotency import idempotent_append
from games.events.vocabulary import NewEvent
from games.models import UserLibrary


def append_one(
    library: UserLibrary,
    event: NewEvent,
    *,
    actor: User,
    idempotency_key: str,
    command_input: dict[str, Any],
    recorded_at: datetime,
    correlation_id: uuid.UUID,
    source_metadata: SourceMetadata,
) -> bool:
    """Append one event. True only when it appended.

    One event per call, never one call per row, for two reasons:
    LockedStream.append() stamps one recorded_at across every row
    of a call, and a removed legacy row carries two instants; and
    one key per fact lets the note and each endpoint replay on
    their own.

    No command_input names an identity a pass mints. Such an
    identity is fresh per pass, so a fingerprint holding one
    answers a second pass with IdempotencyKeyMismatch, in place of
    the drift the gate reads. A PlayerGame id is stable and may be
    named.

    dispatch() is not used: its refusals guard what a person
    states next, and this states what the library recorded.
    """

    def build(stream: LockedStream) -> Sequence[NewEvent]:
        #: The contract passes it; nothing reads it.
        del stream
        return [event]

    outcome = idempotent_append(
        library,
        idempotency_key=idempotency_key,
        command_input=command_input,
        build=build,
        actor=actor,
        correlation_id=correlation_id,
        source_metadata=source_metadata,
        recorded_at=recorded_at,
    )
    #: Positive: an UnchangedAppend appended nothing either.
    return isinstance(outcome, AppendResult)
