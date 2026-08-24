"""Every event type the system knows, and the payload schema each one binds.

An event type is a value -- an `EventSpec` constant naming its schema -- rather
than a member of a closed enum, because an enum member cannot carry a payload
type. A spec generic over its schema turns a wrong payload into a mypy error at
the call site that builds the event, where an enum would have left it to surface
at runtime, under the stream-head lock, inside a command.

The registry is the gate. A type nobody registered cannot be appended and cannot
be replayed, and a registered type's payload is validated against the schema the
spec named. It is an object with a module-level default, exactly as
`ProjectorRegistry` is: a test registers into a registry nobody else sees, so a
test event type never enters the vocabulary an immutable audit trail reads.

The vocabulary below is deliberately empty. The first real event types arrive
with the commands that record them.
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast, is_typeddict

from pydantic import TypeAdapter, ValidationError

from timetracker.temporal import TemporalValue

type AggregateType = str  # "playthrough"

#: What `@with_config` must set for validation to mean anything: extra="forbid"
#: refuses a key nobody declared, strict=True refuses a value pydantic would
#: otherwise quietly coerce.
REQUIRED_SCHEMA_CONFIG: Mapping[str, object] = {"extra": "forbid", "strict": True}


class UnregisteredEventType(ValueError):
    """Raised for an event type no registry knows."""


class PayloadInvalid(ValueError):
    """Raised for a payload its event type's schema refuses."""


class SchemaNotConfigured(TypeError):
    """Raised for a schema declared without the `@with_config` the registry
    requires."""


class VersionNotUpcastable(NotImplementedError):
    """Raised for a registration above version 1, which has no upcaster."""


@dataclass(frozen=True, slots=True)
class EventSpec[PayloadT]:
    """One event type: its name, what it is about, and what its payload holds.

    Frozen and hashable, so a spec is usable as a dict key -- which is how a
    projector family claims the types it handles.
    """

    event_type: str
    #: Declared here and nowhere else. A row storing a copy would keep the old
    #: string after a registration changed, with nothing to notice; asking the
    #: registry instead costs SQL an IN list over event types the index serves.
    aggregate_type: AggregateType
    payload: type[PayloadT]
    version: int = 1

    def new(
        self,
        *,
        aggregate_id: uuid.UUID,
        payload: PayloadT,
        effective_time: TemporalValue | None = None,
        causation_id: uuid.UUID | None = None,
    ) -> NewEvent:
        """Build the event this spec describes.

        The generic parameter is what types `payload`, so an extra key, a
        missing key, or a wrong value type is a mypy error here rather than a
        refusal under the lock.
        """
        return NewEvent(
            spec=self,
            aggregate_id=aggregate_id,
            #: PayloadT is a TypedDict, therefore a dict, which no annotation
            #: over an unbounded parameter can tell a checker.
            payload=cast("dict[str, Any]", payload),
            effective_time=effective_time,
            causation_id=causation_id,
        )


@dataclass(frozen=True, slots=True)
class NewEvent:
    """One fact to append. Carries no stream, sequence, or library: those are
    the stream's to assign, and a caller has no way to express them.

    It carries its spec rather than an event-type string, so the type and its
    schema arrive together and the version is the registry's to stamp.
    """

    spec: EventSpec[Any]
    aggregate_id: uuid.UUID
    payload: dict[str, Any]
    effective_time: TemporalValue | None = None
    causation_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class RegisteredType:
    """A registered spec and the adapter that validates its payloads.

    The adapter is built once, at registration: building one per validation is
    the obvious slow mistake.
    """

    spec: EventSpec[Any]
    adapter: TypeAdapter[Any]


class EventTypeRegistry:
    """The event types that may be appended, and the schema each one validates
    against.

    An object rather than a module-level dict so a caller can hold one of its
    own: a test registers a probe type into a registry nobody else sees, and
    that type never becomes something a production stream could record.
    """

    def __init__(self) -> None:
        self._registered: dict[str, RegisteredType] = {}

    def register(self, spec: EventSpec[Any]) -> None:
        claimed = self._registered.get(spec.event_type)
        if claimed is not None:
            raise ValueError(
                f"{spec.event_type!r} is already registered, by a spec over "
                f"{claimed.spec.payload}. An event type names one schema."
            )

        if not is_typeddict(spec.payload):
            raise TypeError(
                f"{spec.event_type!r} names {spec.payload!r} as its payload, "
                "which is not a TypedDict. A schema is a TypedDict so mypy "
                "checks the payload at the call site that builds the event."
            )

        self._check_schema_config(spec)

        if spec.version != 1:
            raise VersionNotUpcastable(
                f"{spec.event_type!r} registers version {spec.version}. "
                "Nothing upcasts a recorded payload to a newer schema yet, so "
                "a bump would leave every recorded event unreadable. Build the "
                "upcaster first; this refusal relaxes with it."
            )

        self._registered[spec.event_type] = RegisteredType(
            spec=spec, adapter=TypeAdapter(spec.payload)
        )

    @staticmethod
    def _check_schema_config(spec: EventSpec[Any]) -> None:
        """Refuse a schema whose `@with_config` does not say how to validate it.

        The configuration is read off the class rather than off the adapter:
        `with_config` sets `__pydantic_config__`, and reading that mapping is
        what lets the refusal say which key is wrong.
        """
        config = getattr(spec.payload, "__pydantic_config__", None)
        if not isinstance(config, Mapping):
            raise SchemaNotConfigured(
                f"{spec.event_type!r} names {spec.payload.__name__}, which "
                "carries no @with_config. Declare it "
                '@with_config(ConfigDict(extra="forbid", strict=True)).'
            )

        mismatches = [
            f"{key}={config.get(key)!r} rather than {expected!r}"
            for key, expected in REQUIRED_SCHEMA_CONFIG.items()
            if config.get(key) != expected
        ]
        if mismatches:
            raise SchemaNotConfigured(
                f"{spec.event_type!r} names {spec.payload.__name__}, whose "
                f"@with_config sets {', '.join(mismatches)}. Both are required: "
                "without them a payload may carry keys nobody declared and "
                "values pydantic silently coerced."
            )

    def spec_for(self, event_type: str) -> EventSpec[Any]:
        return self._registration_for(event_type).spec

    def validate(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Return the payload as its schema reads it, refusing anything else.

        Pydantic's value is returned rather than the argument, because it is the
        one the schema actually describes -- a field typed `float` given `1`
        comes back as `1.0`, and that is what belongs in the row.
        """
        registration = self._registration_for(event_type)
        try:
            return cast("dict[str, Any]", registration.adapter.validate_python(payload))
        except ValidationError as error:
            raise PayloadInvalid(
                f"This {event_type} payload does not fit "
                f"{registration.spec.payload.__name__}: "
                f"{error.errors(include_url=False)}"
            ) from error

    def __contains__(self, event_type: str) -> bool:
        return event_type in self._registered

    def _registration_for(self, event_type: str) -> RegisteredType:
        try:
            return self._registered[event_type]
        except KeyError:
            raise UnregisteredEventType(
                f"{event_type!r} is not a registered event type. Every event "
                "type is an EventSpec registered in the vocabulary."
            ) from None


DEFAULT_EVENT_TYPES = EventTypeRegistry()
