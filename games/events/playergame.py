"""What a library records about tracked games."""

from typing import TypedDict

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
