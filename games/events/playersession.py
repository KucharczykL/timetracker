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


type InstantText = Annotated[str, AfterValidator(canonical_instant_text)]
type DayText = Annotated[str, AfterValidator(canonical_day_text)]


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
    started_at_zone: str | None
    ended_at: InstantText | None
    ended_at_zone: str | None
    #: The zone the library counts this session's day in.
    day_zone: str


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
    started_at_zone: str | None
    ended_at: InstantText
    ended_at_zone: str | None
    day_zone: str
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
    ended_at_zone: str | None


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
    ended_at_zone: str | None,
    day_zone: str,
) -> NewEvent:
    """The library stated when a session ended.

    `effective_time` carries the end's day. `stated_day_of` and the
    generated `effective_day` read the start instead, so a session
    crossing midnight leaves the two permanently different. The event
    dates the act; the row dates the session.
    """
    return PLAYERSESSION_ENDED.new(
        aggregate_id=session_id,
        effective_time=TemporalValue.parse(
            day_text(ended_at.astimezone(ZoneInfo(day_zone)).date())
        ),
        payload={
            "ended_at": instant_text(ended_at),
            "ended_at_zone": ended_at_zone,
        },
    )
