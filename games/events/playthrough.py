"""What a library records about a run at a game."""

import uuid
from typing import Literal, TypedDict

from pydantic import with_config

from games.events.references import STRICT_SCHEMA, ReferenceId
from games.events.vocabulary import DEFAULT_EVENT_TYPES, EventSpec, NewEvent

#: A Literal, not PlaythroughKind, on purpose.
#: Strict validation refuses a plain string for an enum field, and a recorded
#: payload is read back as one. A test pins these arguments to the choices.
type PlaythroughKindValue = Literal["ordinary", "imported_history"]


@with_config(STRICT_SCHEMA)
class PlaythroughCreatedPayload(TypedDict):
    """The tracked game this run belongs to, and what kind of run it is.

    `player_game` is a bare ReferenceId rather than a Reference for two
    reasons. TrackGame cannot capture one: the PlayerGame row does not
    exist while its build composes this event. And a ReferenceKind for
    PlayerGame would make replay's resolvable-references check read the
    live table before the first row, so a rebuild of a library that has
    lost rows would refuse to run -- which is the drift a rebuild is for.
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
    """The one creation event, for both commands that state one.

    It lives beside the spec rather than in games.commands.playthrough,
    because that module and games.commands.playergame would otherwise
    import each other.
    """
    return PLAYTHROUGH_CREATED.new(
        aggregate_id=uuid.uuid7(),
        payload={"player_game": str(player_game_id), "kind": kind},
    )
