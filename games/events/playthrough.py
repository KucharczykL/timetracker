"""What a library records about a run."""

import uuid
from typing import Literal, TypedDict

from pydantic import with_config

from games.events.references import STRICT_SCHEMA, ReferenceId
from games.events.vocabulary import DEFAULT_EVENT_TYPES, EventSpec, NewEvent
from timetracker.temporal import TemporalValue

#: A Literal, not PlaythroughKind, on purpose. Strict validation refuses a
#: plain string for an enum field, and a recorded payload is read back as
#: one. The recorded vocabulary is frozen; PlaythroughKind is not.
type PlaythroughKindValue = Literal["ordinary", "imported_history"]


@with_config(STRICT_SCHEMA)
class PlaythroughCreatedPayload(TypedDict):
    """The tracked game and the run's kind.

    `player_game` is a bare ReferenceId, not a Reference. TrackGame
    cannot capture one: the PlayerGame row does not exist while its
    build composes this event. And a REQUIRED ReferenceKind for
    PlayerGame would make replay's check read the live table before
    the first row, so a rebuild of a library that lost rows would refuse
    to run -- which is the drift a rebuild is for.
    """

    player_game: ReferenceId
    kind: PlaythroughKindValue


PLAYTHROUGH_CREATED = EventSpec(
    "library.playthrough.created",
    aggregate_type="playthrough",
    payload=PlaythroughCreatedPayload,
)

DEFAULT_EVENT_TYPES.register(PLAYTHROUGH_CREATED)


def playthrough_created(
    player_game_id: uuid.UUID,
    *,
    kind: PlaythroughKindValue = "ordinary",
) -> NewEvent:
    """The one creation event, for both commands."""
    return PLAYTHROUGH_CREATED.new(
        aggregate_id=uuid.uuid7(),
        payload={"player_game": str(player_game_id), "kind": kind},
    )


@with_config(STRICT_SCHEMA)
class PlaythroughEndpointPayload(TypedDict):
    """The note of one endpoint, and only that.

    The date is `effective_time`, which is where the charter puts what
    a player says happened. No note is the empty string: an optional
    key would ask a reader whether a value is absent or empty, and
    here the two mean one thing.

    One type for both specs. They are two EventSpecs, so an issue that
    gives one of them a field gives it a type of its own.
    """

    note: str


PLAYTHROUGH_STARTED = EventSpec(
    "library.playthrough.started",
    aggregate_type="playthrough",
    payload=PlaythroughEndpointPayload,
)

PLAYTHROUGH_COMPLETED = EventSpec(
    "library.playthrough.completed",
    aggregate_type="playthrough",
    payload=PlaythroughEndpointPayload,
)

DEFAULT_EVENT_TYPES.register(PLAYTHROUGH_STARTED)
DEFAULT_EVENT_TYPES.register(PLAYTHROUGH_COMPLETED)


def playthrough_started(
    playthrough_id: uuid.UUID,
    *,
    when: TemporalValue | None,
    note: str,
) -> NewEvent:
    """The run began, on the day stated or on none."""
    #: The aggregate exists, so the id is given rather than minted.
    return PLAYTHROUGH_STARTED.new(
        aggregate_id=playthrough_id,
        effective_time=when,
        payload={"note": note},
    )


def playthrough_completed(
    playthrough_id: uuid.UUID,
    *,
    when: TemporalValue | None,
    note: str,
) -> NewEvent:
    """The run met its main objective."""
    return PLAYTHROUGH_COMPLETED.new(
        aggregate_id=playthrough_id,
        effective_time=when,
        payload={"note": note},
    )
