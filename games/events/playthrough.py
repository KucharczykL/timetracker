"""What a library records about a run."""

import uuid
from typing import Literal, TypedDict

from pydantic import with_config

from games.events.endpoint import EndpointPayload, endpoint_events
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
class PlaythroughStartVoidedPayload(TypedDict):
    """The library takes back the record of a start."""


@with_config(STRICT_SCHEMA)
class PlaythroughCompletionVoidedPayload(TypedDict):
    """The library takes back the record of a completion."""


PLAYTHROUGH_START_EVENTS = endpoint_events(
    "playthrough",
    stated="library.playthrough.started",
    corrected="library.playthrough.start_corrected",
    voided="library.playthrough.start_voided",
    payload=EndpointPayload,
    voided_payload=PlaythroughStartVoidedPayload,
)
PLAYTHROUGH_COMPLETION_EVENTS = endpoint_events(
    "playthrough",
    stated="library.playthrough.completed",
    corrected="library.playthrough.completion_corrected",
    voided="library.playthrough.completion_voided",
    payload=EndpointPayload,
    voided_payload=PlaythroughCompletionVoidedPayload,
)
PLAYTHROUGH_STARTED = PLAYTHROUGH_START_EVENTS.stated
PLAYTHROUGH_START_CORRECTED = PLAYTHROUGH_START_EVENTS.corrected
PLAYTHROUGH_START_VOIDED = PLAYTHROUGH_START_EVENTS.voided
PLAYTHROUGH_COMPLETED = PLAYTHROUGH_COMPLETION_EVENTS.stated
PLAYTHROUGH_COMPLETION_CORRECTED = PLAYTHROUGH_COMPLETION_EVENTS.corrected
PLAYTHROUGH_COMPLETION_VOIDED = PLAYTHROUGH_COMPLETION_EVENTS.voided


def playthrough_start_voided(playthrough_id: uuid.UUID) -> NewEvent:
    """The run states no start again; no day."""
    return PLAYTHROUGH_START_VOIDED.new(aggregate_id=playthrough_id, payload={})


def playthrough_completion_voided(playthrough_id: uuid.UUID) -> NewEvent:
    """The run states no completion again."""
    return PLAYTHROUGH_COMPLETION_VOIDED.new(aggregate_id=playthrough_id, payload={})


@with_config(STRICT_SCHEMA)
class PlaythroughNamePayload(TypedDict):
    """What the library calls this run. Blank reads as its number."""

    name: str


@with_config(STRICT_SCHEMA)
class PlaythroughNotePayload(TypedDict):
    """The note of the whole run.

    Not `EndpointPayload`, though the shape is the same:
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


@with_config(STRICT_SCHEMA)
class PlaythroughMovedPayload(TypedDict):
    """The run's new tracked game; bare id."""

    player_game: ReferenceId


PLAYTHROUGH_MOVED = EventSpec(
    "library.playthrough.moved",
    aggregate_type="playthrough",
    payload=PlaythroughMovedPayload,
)

DEFAULT_EVENT_TYPES.register(PLAYTHROUGH_MOVED)


def playthrough_moved(
    playthrough_id: uuid.UUID, *, player_game_id: uuid.UUID
) -> NewEvent:
    """The run belongs to another game now."""
    return PLAYTHROUGH_MOVED.new(
        aggregate_id=playthrough_id, payload={"player_game": str(player_game_id)}
    )
