"""Every event type and its payload schema."""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast, is_typeddict

from pydantic import TypeAdapter, ValidationError

from games.events.references import (
    DEFAULT_REFERENCE_KINDS,
    FoundReference,
    ReferenceFields,
    ReferenceKindRegistry,
    UnknownReferenceKind,
    check_kinds_registered,
    reference_fields,
    references_in,
)
from games.models import LibraryEvent
from timetracker.temporal import TemporalValue

type AggregateType = str  # "playthrough"
type EventType = str  # "library.session.created"

#: Without both, validation means nothing.
REQUIRED_SCHEMA_CONFIG: Mapping[str, object] = {"extra": "forbid", "strict": True}

#: Read off the column, so nothing drifts.
EVENT_TYPE_MAX_LENGTH: int = cast(
    int, LibraryEvent._meta.get_field("event_type").max_length
)


class UnregisteredEventType(ValueError):
    """Raised for an unregistered event type."""


class EventNameInvalid(ValueError):
    """Raised for a spec's unusable name."""


class PayloadInvalid(ValueError):
    """Raised for a payload its schema refuses."""


class SchemaNotConfigured(TypeError):
    """Raised for a schema without `@with_config`."""


class VersionNotUpcastable(NotImplementedError):
    """Raised for a version above 1."""


@dataclass(frozen=True, slots=True)
class EventSpec[PayloadT]:
    """One event type: name, aggregate, payload schema."""

    event_type: EventType
    #: Declared here only; no row copies it.
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
        """Build the event this spec describes."""
        return NewEvent(
            spec=self,
            aggregate_id=aggregate_id,
            #: PayloadT is a TypedDict, therefore a dict.
            payload=cast("dict[str, Any]", payload),
            effective_time=effective_time,
            causation_id=causation_id,
        )


@dataclass(frozen=True, slots=True)
class NewEvent:
    """One fact to append; build with spec.new()."""

    spec: EventSpec[Any]
    aggregate_id: uuid.UUID
    payload: dict[str, Any]
    effective_time: TemporalValue | None = None
    causation_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class Unchanged:
    """The state the caller asks for already holds, so there is nothing to
    record. The other thing a command's build may return.

    `reason` is for a log line and for a test that must name which branch
    decided. Nothing user-facing may depend on it: a repeated delivery answers
    from the idempotency record, before the build that writes the sentence runs.
    """

    reason: str


@dataclass(frozen=True, slots=True)
class RegisteredType:
    """A registered spec, its adapter, its references."""

    spec: EventSpec[Any]
    adapter: TypeAdapter[Any]
    #: Derived from the payload's annotations at registration.
    references: ReferenceFields


class EventTypeRegistry:
    """The event types that may be appended."""

    def __init__(
        self, reference_kinds: ReferenceKindRegistry = DEFAULT_REFERENCE_KINDS
    ) -> None:
        self._registered: dict[EventType, RegisteredType] = {}
        self._reference_kinds = reference_kinds

    def register(self, spec: EventSpec[Any]) -> None:
        self._check_names(spec)

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
            spec=spec,
            adapter=TypeAdapter(spec.payload),
            #: Raises rather than record an unenumerable reference.
            references=reference_fields(spec.payload),
        )

    @staticmethod
    def _check_names(spec: EventSpec[Any]) -> None:
        """Refuse a spec's empty or over-long name."""
        if not spec.event_type:
            raise EventNameInvalid(
                f"{spec.payload!r} registers under an empty event type. An "
                "event type is the name a recorded event is read back by."
            )
        if len(spec.event_type) > EVENT_TYPE_MAX_LENGTH:
            raise EventNameInvalid(
                f"{spec.event_type!r} is {len(spec.event_type)} characters; an "
                f"event type is at most {EVENT_TYPE_MAX_LENGTH}, the width of "
                "the column every event stores it in."
            )
        if not spec.aggregate_type:
            raise EventNameInvalid(
                f"{spec.event_type!r} names an empty aggregate type. It says "
                "what the event is about and is declared here and nowhere "
                "else, so no column and no constraint can catch it later."
            )

    @staticmethod
    def _check_schema_config(spec: EventSpec[Any]) -> None:
        """Refuse a schema without the required config."""
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

    def spec_for(self, event_type: EventType) -> EventSpec[Any]:
        return self._registration_for(event_type).spec

    def reference_fields_for(self, event_type: EventType) -> ReferenceFields:
        """Which of this payload's fields hold references."""
        return self._registration_for(event_type).references

    def references_in(
        self, event_type: EventType, payload: Mapping[str, Any]
    ) -> tuple[FoundReference, ...]:
        """Every reference this recorded payload carries."""
        return tuple(
            references_in(payload, self._registration_for(event_type).references)
        )

    @property
    def reference_kinds(self) -> ReferenceKindRegistry:
        """The kinds payload references validate against."""
        return self._reference_kinds

    def validate(
        self, event_type: EventType, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Return the payload its schema reads."""
        registration = self._registration_for(event_type)
        try:
            validated = cast(
                "dict[str, Any]", registration.adapter.validate_python(payload)
            )
        except ValidationError as error:
            raise PayloadInvalid(
                f"This {event_type} payload does not fit "
                f"{registration.spec.payload.__name__}: "
                f"{error.errors(include_url=False)}"
            ) from error
        try:
            check_kinds_registered(
                validated, registration.references, self._reference_kinds
            )
        except UnknownReferenceKind as error:
            raise PayloadInvalid(
                f"This {event_type} payload cannot be recorded: {error}"
            ) from error
        return validated

    def __contains__(self, event_type: EventType) -> bool:
        return event_type in self._registered

    def _registration_for(self, event_type: EventType) -> RegisteredType:
        try:
            return self._registered[event_type]
        except KeyError:
            raise UnregisteredEventType(
                f"{event_type!r} is not a registered event type. Every event "
                "type is an EventSpec registered in the vocabulary."
            ) from None


DEFAULT_EVENT_TYPES = EventTypeRegistry()
