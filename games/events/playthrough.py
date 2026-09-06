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
    playthrough_id: uuid.UUID | None = None,
) -> NewEvent:
    """The one creation event, for both commands.

    A caller states the identity where order matters: #684 records
    a past instant, and the identity audit holds every Playthrough
    key to its `created_at` order.
    """
    return PLAYTHROUGH_CREATED.new(
        aggregate_id=uuid.uuid7() if playthrough_id is None else playthrough_id,
        payload={"player_game": str(player_game_id), "kind": kind},
    )


@with_config(STRICT_SCHEMA)
class PlaythroughEndpointPayload(TypedDict):
    """The note of one endpoint, and only that.

    The date is `effective_time`, which is where the charter puts what
    a player says happened. No note is the empty string: an optional
    key would ask a reader whether a value is absent or empty, and
    here the two mean one thing.

    One type for the four specs about an endpoint. Each is its own
    EventSpec, so an issue that gives one of them a field gives it a
    type of its own, and the rows already written keep reading back.
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


PLAYTHROUGH_START_CORRECTED = EventSpec(
    "library.playthrough.start_corrected",
    aggregate_type="playthrough",
    payload=PlaythroughEndpointPayload,
)

PLAYTHROUGH_COMPLETION_CORRECTED = EventSpec(
    "library.playthrough.completion_corrected",
    aggregate_type="playthrough",
    payload=PlaythroughEndpointPayload,
)

DEFAULT_EVENT_TYPES.register(PLAYTHROUGH_START_CORRECTED)
DEFAULT_EVENT_TYPES.register(PLAYTHROUGH_COMPLETION_CORRECTED)


def playthrough_start_corrected(
    playthrough_id: uuid.UUID,
    *,
    when: TemporalValue | None,
    note: str,
) -> NewEvent:
    """The run began on the day now stated, or on none."""
    return PLAYTHROUGH_START_CORRECTED.new(
        aggregate_id=playthrough_id,
        effective_time=when,
        payload={"note": note},
    )


def playthrough_completion_corrected(
    playthrough_id: uuid.UUID,
    *,
    when: TemporalValue | None,
    note: str,
) -> NewEvent:
    """The run met its main objective on the day now stated, or on none."""
    return PLAYTHROUGH_COMPLETION_CORRECTED.new(
        aggregate_id=playthrough_id,
        effective_time=when,
        payload={"note": note},
    )


@with_config(STRICT_SCHEMA)
class PlaythroughNamePayload(TypedDict):
    """What the library calls this run. Blank reads as its number."""

    name: str


@with_config(STRICT_SCHEMA)
class PlaythroughNotePayload(TypedDict):
    """The note of the whole run.

    Not `PlaythroughEndpointPayload`, though the shape is the same:
    that note belongs to an act, and its day is the effective_time.
    This one describes a run and has no day.
    """

    note: str


PLAYTHROUGH_NAME_CHANGED = EventSpec(
    "library.playthrough.name_changed",
    aggregate_type="playthrough",
    payload=PlaythroughNamePayload,
)

PLAYTHROUGH_NOTE_CHANGED = EventSpec(
    "library.playthrough.note_changed",
    aggregate_type="playthrough",
    payload=PlaythroughNotePayload,
)

DEFAULT_EVENT_TYPES.register(PLAYTHROUGH_NAME_CHANGED)
DEFAULT_EVENT_TYPES.register(PLAYTHROUGH_NOTE_CHANGED)


def playthrough_name_changed(playthrough_id: uuid.UUID, *, name: str) -> NewEvent:
    """The library calls the run this now."""
    #: No effective_time: a rename happens on no day.
    return PLAYTHROUGH_NAME_CHANGED.new(
        aggregate_id=playthrough_id, payload={"name": name}
    )


def playthrough_note_changed(playthrough_id: uuid.UUID, *, note: str) -> NewEvent:
    """The note of the run, as it now reads."""
    return PLAYTHROUGH_NOTE_CHANGED.new(
        aggregate_id=playthrough_id, payload={"note": note}
    )


@with_config(STRICT_SCHEMA)
class PlaythroughRemovedPayload(TypedDict):
    """The library takes the run out."""


@with_config(STRICT_SCHEMA)
class PlaythroughRestoredPayload(TypedDict):
    """The library puts the run back."""


PLAYTHROUGH_REMOVED = EventSpec(
    "library.playthrough.removed",
    aggregate_type="playthrough",
    payload=PlaythroughRemovedPayload,
)

PLAYTHROUGH_RESTORED = EventSpec(
    "library.playthrough.restored",
    aggregate_type="playthrough",
    payload=PlaythroughRestoredPayload,
)

DEFAULT_EVENT_TYPES.register(PLAYTHROUGH_REMOVED)
DEFAULT_EVENT_TYPES.register(PLAYTHROUGH_RESTORED)


def playthrough_removed(playthrough_id: uuid.UUID) -> NewEvent:
    """The run leaves the lists."""
    return PLAYTHROUGH_REMOVED.new(aggregate_id=playthrough_id, payload={})


def playthrough_restored(playthrough_id: uuid.UUID) -> NewEvent:
    """The run returns to the lists."""
    return PLAYTHROUGH_RESTORED.new(aggregate_id=playthrough_id, payload={})
