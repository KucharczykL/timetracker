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
    """Append one event; true when it appended.

    One event per call. A call stamps one recorded_at
    across its rows, and one key per fact lets each
    fact replay alone.

    No command_input names an identity the call mints
    here. Such a value is fresh every pass, so a second
    pass would read IdempotencyKeyMismatch in place of
    the no-op the key promises. A stable identity the
    caller was handed is fine, and both passes name one.
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
    #: False says the key already ran, which is a
    #: ReplayedAppend. build always answers one event,
    #: so UnchangedAppend cannot reach this line. Both
    #: read alike here: no caller counts a replay apart.
    return isinstance(outcome, AppendResult)
