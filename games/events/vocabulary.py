"""Every event type and its payload schema."""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import (
    Any,
    NamedTuple,
    NotRequired,
    Required,
    TypeAliasType,
    cast,
    get_args,
    get_origin,
    get_type_hints,
    is_typeddict,
)

from pydantic import TypeAdapter, ValidationError

from games.events.references import (
    DEFAULT_REFERENCE_KINDS,
    FoundReference,
    Reference,
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
type EventType = str  # "library.playersession.created"
#: Path from payload to one field.
type KeyPath = tuple[str, ...]
#: A `type` alias's name: "ReferenceId".
type AliasName = str
type AliasedFields = Mapping[AliasName, tuple[KeyPath, ...]]

AGGREGATE_ID_ALIAS: AliasName = "ReferenceId"
INSTANT_ALIAS: AliasName = "InstantText"
DAY_ALIAS: AliasName = "DayText"


class DatedKeys(NamedTuple):
    """Instant paths, and day paths."""

    instants: tuple[KeyPath, ...]
    days: tuple[KeyPath, ...]


def aliased_fields(payload: type) -> AliasedFields:
    """Aliased fields, by alias name, nested.

    A `Reference` is re-captured whole: its `id` is no
    aggregate key, so the walk stops at one.
    """
    found: dict[AliasName, list[KeyPath]] = {}
    _collect_aliases(payload, (), found, frozenset())
    return {name: tuple(paths) for name, paths in found.items()}


def _collect_aliases(
    hint: Any,
    path: KeyPath,
    found: dict[AliasName, list[KeyPath]],
    seen: frozenset[Any],
) -> None:
    if isinstance(hint, TypeAliasType):
        paths = found.setdefault(hint.__name__, [])
        if path not in paths:
            paths.append(path)
        _collect_aliases(hint.__value__, path, found, seen)
        return
    if get_origin(hint) in (Required, NotRequired) or hasattr(hint, "__metadata__"):
        _collect_aliases(get_args(hint)[0], path, found, seen)
        return
    if hint is Reference:
        return
    if is_typeddict(hint):
        if hint in seen:
            return
        for key, field in get_type_hints(hint, include_extras=True).items():
            _collect_aliases(field, (*path, key), found, seen | {hint})
        return
    for argument in get_args(hint):
        _collect_aliases(argument, path, found, seen)


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
    aliased: AliasedFields


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
            aliased=aliased_fields(spec.payload),
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

    def event_types_for(self, aggregate_type: AggregateType) -> frozenset[EventType]:
        """Every event type that speaks about this aggregate.

        An event row states its type and never its aggregate type, so a
        read that wants one aggregate's rows asks here for the types to
        filter on. An aggregate type nothing declares names no type.
        """
        return frozenset(
            event_type
            for event_type, registered in self._registered.items()
            if registered.spec.aggregate_type == aggregate_type
        )

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

    def aggregate_id_keys(self, event_type: EventType) -> tuple[KeyPath, ...]:
        """Paths holding a bare aggregate id."""
        return self._registration_for(event_type).aliased.get(AGGREGATE_ID_ALIAS, ())

    def dated_keys(self, event_type: EventType) -> DatedKeys:
        """Paths stating an instant or day."""
        aliased = self._registration_for(event_type).aliased
        return DatedKeys(
            instants=aliased.get(INSTANT_ALIAS, ()), days=aliased.get(DAY_ALIAS, ())
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
