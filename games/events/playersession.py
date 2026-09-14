"""What a library records about one session."""

import uuid
from datetime import UTC, date, datetime
from typing import Annotated, Literal, TypedDict
from zoneinfo import ZoneInfo

from pydantic import AfterValidator, Field, with_config

from games.events.references import STRICT_SCHEMA, Reference, ReferenceId
from games.events.vocabulary import DEFAULT_EVENT_TYPES, EventSpec, NewEvent
from timetracker.temporal import TemporalValue


def instant_text(value: datetime) -> str:
    """One instant, one spelling: UTC, ISO-8601."""
    return value.astimezone(UTC).isoformat()


def instant_from_text(value: str) -> datetime:
    """The instant a payload carries."""
    return datetime.fromisoformat(value)


def day_text(value: date) -> str:
    """One day, one spelling."""
    return value.isoformat()


def day_from_text(value: str) -> date:
    """The day a payload carries."""
    return date.fromisoformat(value)


def canonical_instant_text(value: str) -> str:
    """Refuse an instant spelled any other way.

    A payload carries the form it is read back in, as `ReferenceId`
    does for a key. Without this, `Z` and `+00:00` and a local offset
    all record one instant three ways, strict validation admits every
    one of them, and a replay -- which re-validates nothing -- meets
    the malformed one inside the projector.
    """
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{value!r} is not an ISO-8601 instant.") from None
    if parsed.tzinfo is None:
        raise ValueError(f"{value!r} states no offset, so it names no instant.")
    canonical = instant_text(parsed)
    if canonical != value:
        raise ValueError(f"{value!r} is not canonical; {canonical!r} is.")
    return value


def canonical_day_text(value: str) -> str:
    """Refuse a day spelled any other way."""
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{value!r} is not an ISO-8601 day.") from None
    canonical = day_text(parsed)
    if canonical != value:
        raise ValueError(f"{value!r} is not canonical; {canonical!r} is.")
    return value


def stated_zone_text(value: str) -> str:
    """Refuse a zone name nobody could have stated.

    Null is how an unstated zone is spelled, so a blank string is a
    second spelling of it, and a padded one is a second spelling of
    the name inside it. Both reach the projector unvalidated on a
    replay, where the blank meets `playersession_zone_not_blank` as
    an IntegrityError nothing can repair.
    """
    if not value or value != value.strip():
        raise ValueError(f"{value!r} is not a zone name; null is an unstated zone.")
    return value


type InstantText = Annotated[str, AfterValidator(canonical_instant_text)]
type DayText = Annotated[str, AfterValidator(canonical_day_text)]
type ZoneText = Annotated[str, AfterValidator(stated_zone_text)]

#: The zone a clock or a calendar is read in, e.g. "Europe/Prague".
type ZoneName = str


@with_config(STRICT_SCHEMA)
class TimedTimingPayload(TypedDict):
    """An exact start, an end once there is one, no override."""

    #: A bare Literal, not PlayerSessionTimingMode and not an alias
    #: for one: strict validation refuses a plain string for an enum
    #: field, and the discriminator reads the annotation itself, so a
    #: PEP 695 alias hides the tag it needs.
    mode: Literal["timed"]
    started_at: InstantText
    #: The zone the clock stood in, or None where nobody stated it.
    started_at_zone: ZoneText | None
    ended_at: InstantText | None
    ended_at_zone: ZoneText | None
    #: The zone the library counts this session's day in.
    day_zone: ZoneText


@with_config(STRICT_SCHEMA)
class DurationOnlyTimingPayload(TypedDict):
    """A written calendar day and a duration. No instants.

    The day states no zone, because no zone converts it.
    """

    mode: Literal["duration_only"]
    stated_day: DayText
    duration_seconds: int


@with_config(STRICT_SCHEMA)
class CorrectedTimingPayload(TypedDict):
    """Both instants, and an override that replaces the elapsed time."""

    mode: Literal["corrected"]
    started_at: InstantText
    started_at_zone: ZoneText | None
    ended_at: InstantText
    ended_at_zone: ZoneText | None
    day_zone: ZoneText
    duration_seconds: int


#: One whole statement about a session's time. A partial act -- an end
#: stated on a running session -- carries a payload of its own.
type TimingPayload = Annotated[
    TimedTimingPayload | DurationOnlyTimingPayload | CorrectedTimingPayload,
    Field(discriminator="mode"),
]


@with_config(STRICT_SCHEMA)
class PlayerSessionCreatedPayload(TypedDict):
    """The run this session belongs to, and what it states.

    `playthrough` is a bare ReferenceId, not a Reference, as
    `PlaythroughCreatedPayload.player_game` is: a REQUIRED
    ReferenceKind for a projection would make replay's check read the
    live table before the first row, so a rebuild of a library that
    lost rows would refuse to run.

    `release` is reserved and always None. A key holding None rather
    than an absent one, because under `extra="forbid"` the two would
    be two spellings of one fact. A key added to this payload later
    is a NotRequired one, since nothing upcasts a recorded payload.
    """

    playthrough: ReferenceId
    device: Reference | None
    release: Reference | None
    timing: TimingPayload
    note: str
    emulated: bool


PLAYERSESSION_CREATED = EventSpec(
    "library.playersession.created",
    aggregate_type="playersession",
    payload=PlayerSessionCreatedPayload,
)

DEFAULT_EVENT_TYPES.register(PLAYERSESSION_CREATED)


def stated_day_of(timing: TimingPayload) -> date:
    """The day this statement lands on.

    A written day for a duration-only statement, and the start read
    in the zone the library counts days in for the other two -- the
    same rule `effective_day` generates in the database.
    """
    if timing["mode"] == "duration_only":
        return day_from_text(timing["stated_day"])
    started = instant_from_text(timing["started_at"])
    return started.astimezone(ZoneInfo(timing["day_zone"])).date()


def playersession_created(
    playthrough_id: uuid.UUID,
    *,
    timing: TimingPayload,
    device: Reference | None,
    release: Reference | None,
    note: str,
    emulated: bool,
    session_id: uuid.UUID | None = None,
) -> NewEvent:
    """The library recorded a session at a run.

    A caller states the identity where one already exists: the
    conversion records a past session under the key it has always
    had, so every link to it keeps working.

    `effective_time` carries the day, which is what the envelope's
    field is for. It bottoms out at day precision, so the instant
    cannot go there, and a reader after the day need not open the
    payload and branch on the mode to find one.
    """
    return PLAYERSESSION_CREATED.new(
        aggregate_id=uuid.uuid7() if session_id is None else session_id,
        effective_time=TemporalValue.parse(day_text(stated_day_of(timing))),
        payload={
            "playthrough": str(playthrough_id),
            "device": device,
            "release": release,
            "timing": timing,
            "note": note,
            "emulated": emulated,
        },
    )


@with_config(STRICT_SCHEMA)
class PlayerSessionEndedPayload(TypedDict):
    """Two columns; the row holds day_zone."""

    ended_at: InstantText
    ended_at_zone: ZoneText | None


PLAYERSESSION_ENDED = EventSpec(
    "library.playersession.ended",
    aggregate_type="playersession",
    payload=PlayerSessionEndedPayload,
)

DEFAULT_EVENT_TYPES.register(PLAYERSESSION_ENDED)


def playersession_ended(
    session_id: uuid.UUID,
    *,
    ended_at: datetime,
    ended_at_zone: ZoneName | None,
    day_zone: ZoneInfo,
) -> NewEvent:
    """The library stated when a session ended.

    `effective_time` carries the end's day. `stated_day_of` and the
    generated `effective_day` read the start instead, so a session
    crossing midnight in `day_zone` leaves the two permanently
    different. The event dates the act; the row dates the session.

    `day_zone` is a resolved zone rather than its name, because the
    name comes off a row this command did not write. A name tzdata
    has since lost would raise `ZoneInfoNotFoundError` here -- a
    `KeyError`, which the boundary does not answer -- so the caller
    resolves it where a refusal can still carry a sentence.
    """
    return PLAYERSESSION_ENDED.new(
        aggregate_id=session_id,
        effective_time=TemporalValue.parse(
            day_text(ended_at.astimezone(day_zone).date())
        ),
        payload={
            "ended_at": instant_text(ended_at),
            "ended_at_zone": ended_at_zone,
        },
    )


@with_config(STRICT_SCHEMA)
class PlayerSessionTimingCorrectedPayload(TypedDict):
    """A whole timing statement."""

    timing: TimingPayload


PLAYERSESSION_TIMING_CORRECTED = EventSpec(
    "library.playersession.timing_corrected",
    aggregate_type="playersession",
    payload=PlayerSessionTimingCorrectedPayload,
)

DEFAULT_EVENT_TYPES.register(PLAYERSESSION_TIMING_CORRECTED)


def playersession_timing_corrected(
    session_id: uuid.UUID, *, timing: TimingPayload
) -> NewEvent:
    """Dated by the new statement's day, never the end."""
    return PLAYERSESSION_TIMING_CORRECTED.new(
        aggregate_id=session_id,
        effective_time=TemporalValue.parse(day_text(stated_day_of(timing))),
        payload={"timing": timing},
    )


@with_config(STRICT_SCHEMA)
class PlayerSessionNoteChangedPayload(TypedDict):
    """An empty note clears it."""

    note: str


PLAYERSESSION_NOTE_CHANGED = EventSpec(
    "library.playersession.note_changed",
    aggregate_type="playersession",
    payload=PlayerSessionNoteChangedPayload,
)

DEFAULT_EVENT_TYPES.register(PLAYERSESSION_NOTE_CHANGED)


def playersession_note_changed(session_id: uuid.UUID, *, note: str) -> NewEvent:
    """A session's note; dated on no day."""
    return PLAYERSESSION_NOTE_CHANGED.new(
        aggregate_id=session_id, payload={"note": note}
    )


@with_config(STRICT_SCHEMA)
class PlayerSessionDeviceChangedPayload(TypedDict):
    """A Reference, so the index reads it."""

    device: Reference | None


PLAYERSESSION_DEVICE_CHANGED = EventSpec(
    "library.playersession.device_changed",
    aggregate_type="playersession",
    payload=PlayerSessionDeviceChangedPayload,
)

DEFAULT_EVENT_TYPES.register(PLAYERSESSION_DEVICE_CHANGED)


def playersession_device_changed(
    session_id: uuid.UUID, *, device: Reference | None
) -> NewEvent:
    """A session's device, or none."""
    return PLAYERSESSION_DEVICE_CHANGED.new(
        aggregate_id=session_id, payload={"device": device}
    )


@with_config(STRICT_SCHEMA)
class PlayerSessionEmulatedChangedPayload(TypedDict):
    """Whether the session was emulated."""

    emulated: bool


PLAYERSESSION_EMULATED_CHANGED = EventSpec(
    "library.playersession.emulated_changed",
    aggregate_type="playersession",
    payload=PlayerSessionEmulatedChangedPayload,
)

DEFAULT_EVENT_TYPES.register(PLAYERSESSION_EMULATED_CHANGED)


def playersession_emulated_changed(
    session_id: uuid.UUID, *, emulated: bool
) -> NewEvent:
    """Whether a session was emulated."""
    return PLAYERSESSION_EMULATED_CHANGED.new(
        aggregate_id=session_id, payload={"emulated": emulated}
    )


@with_config(STRICT_SCHEMA)
class PlayerSessionMovedPayload(TypedDict):
    """A bare key, as the creation's run."""

    playthrough: ReferenceId


PLAYERSESSION_MOVED = EventSpec(
    "library.playersession.moved",
    aggregate_type="playersession",
    payload=PlayerSessionMovedPayload,
)

DEFAULT_EVENT_TYPES.register(PLAYERSESSION_MOVED)


def playersession_moved(
    session_id: uuid.UUID, *, playthrough_id: uuid.UUID
) -> NewEvent:
    """The run a session now belongs to."""
    return PLAYERSESSION_MOVED.new(
        aggregate_id=session_id, payload={"playthrough": str(playthrough_id)}
    )
