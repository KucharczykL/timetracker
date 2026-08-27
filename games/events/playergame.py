"""What a library records about tracked games."""

from typing import Literal, TypedDict

from pydantic import with_config

from games.events.references import STRICT_SCHEMA, Reference
from games.events.vocabulary import DEFAULT_EVENT_TYPES, EventSpec


@with_config(STRICT_SCHEMA)
class PlayerGameCreatedPayload(TypedDict):
    """The catalog game this library began tracking."""

    game: Reference


PLAYERGAME_CREATED = EventSpec(
    "library.playergame.created",
    aggregate_type="playergame",
    payload=PlayerGameCreatedPayload,
)

DEFAULT_EVENT_TYPES.register(PLAYERGAME_CREATED)


#: A Literal, not PlayerGameStatus, on purpose.
#: Strict validation refuses a plain string for an enum field, and a recorded
#: payload is read back as one. A test pins these arguments to the choices.
type StatusValue = Literal[
    "unplayed", "played", "completed", "retired", "shelved", "abandoned"
]


@with_config(STRICT_SCHEMA)
class PlayerGameStatusChangedPayload(TypedDict):
    """The status this library now gives."""

    status: StatusValue


PLAYERGAME_STATUS_CHANGED = EventSpec(
    "library.playergame.status_changed",
    aggregate_type="playergame",
    payload=PlayerGameStatusChangedPayload,
)

DEFAULT_EVENT_TYPES.register(PLAYERGAME_STATUS_CHANGED)


@with_config(STRICT_SCHEMA)
class PlayerGameMasteredChangedPayload(TypedDict):
    """Whether this library now masters the game."""

    mastered: bool


PLAYERGAME_MASTERED_CHANGED = EventSpec(
    "library.playergame.mastered_changed",
    aggregate_type="playergame",
    payload=PlayerGameMasteredChangedPayload,
)

DEFAULT_EVENT_TYPES.register(PLAYERGAME_MASTERED_CHANGED)


@with_config(STRICT_SCHEMA)
class PlayerGameExcludedFromUnfinishedChangedPayload(TypedDict):
    """Whether unfinished lists now omit the game."""

    excluded_from_unfinished: bool


PLAYERGAME_EXCLUDED_FROM_UNFINISHED_CHANGED = EventSpec(
    "library.playergame.excluded_from_unfinished_changed",
    aggregate_type="playergame",
    payload=PlayerGameExcludedFromUnfinishedChangedPayload,
)

DEFAULT_EVENT_TYPES.register(PLAYERGAME_EXCLUDED_FROM_UNFINISHED_CHANGED)


@with_config(STRICT_SCHEMA)
class PlayerGameArchivedPayload(TypedDict):
    """The library now archives the game."""


PLAYERGAME_ARCHIVED = EventSpec(
    "library.playergame.archived",
    aggregate_type="playergame",
    payload=PlayerGameArchivedPayload,
)

DEFAULT_EVENT_TYPES.register(PLAYERGAME_ARCHIVED)


@with_config(STRICT_SCHEMA)
class PlayerGameRestoredPayload(TypedDict):
    """The library restores the game."""


PLAYERGAME_RESTORED = EventSpec(
    "library.playergame.restored",
    aggregate_type="playergame",
    payload=PlayerGameRestoredPayload,
)

DEFAULT_EVENT_TYPES.register(PLAYERGAME_RESTORED)
