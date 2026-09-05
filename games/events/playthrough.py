"""What a library records about a run."""

import uuid
from typing import Literal, TypedDict

from pydantic import with_config

from games.events.references import STRICT_SCHEMA, ReferenceId
from games.events.vocabulary import DEFAULT_EVENT_TYPES, EventSpec, NewEvent

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
