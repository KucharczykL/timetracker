"""What a library records about the catalog games it tracks.

The first production vocabulary. Until now `DEFAULT_EVENT_TYPES` was empty by
design; registering happens at import, and `games/projectors/playergame.py`
imports this module, which `GamesConfig.ready()` reaches through the projector
package.
"""

from typing import TypedDict

from pydantic import with_config

from games.events.references import STRICT_SCHEMA, Reference
from games.events.vocabulary import DEFAULT_EVENT_TYPES, EventSpec


@with_config(STRICT_SCHEMA)
class PlayerGameCreatedPayload(TypedDict):
    """The catalog game this library began tracking.

    One key. The library is on the envelope, the identity is the aggregate_id,
    and the time is recorded_at; repeating any of them here would be a second
    copy of a fact the event already carries.
    """

    game: Reference


PLAYERGAME_CREATED = EventSpec(
    "library.playergame.created",
    aggregate_type="playergame",
    payload=PlayerGameCreatedPayload,
)

DEFAULT_EVENT_TYPES.register(PLAYERGAME_CREATED)
