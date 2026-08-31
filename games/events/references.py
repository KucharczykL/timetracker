"""What an event records about a row."""

import types
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import (
    Annotated,
    Any,
    NamedTuple,
    NotRequired,
    Required,
    TypedDict,
    Union,
    get_args,
    get_origin,
    get_type_hints,
    is_typeddict,
)

from django.db import models
from pydantic import AfterValidator, ConfigDict, with_config

from games.models import Device, Game, Platform, Release
from timetracker.uuidv7 import UUIDv7ParseError, parse_uuidv7

type ReferenceKindName = str  # "catalog.game"
type PayloadKey = str  # "device"

#: Spelled here; importing the vocabulary would cycle.
STRICT_SCHEMA = ConfigDict(extra="forbid", strict=True)


class UnknownReferenceKind(ValueError):
    """Raised for an unregistered kind name."""


class UnmappedReferenceModel(TypeError):
    """Raised for a model no kind captures."""


class ReferenceFieldUnsupported(TypeError):
    """Raised for an annotation nothing can enumerate."""


def canonical_uuid_text(value: str) -> str:
    """Refuse anything but canonical UUIDv7 text.

    Do not make the text canonical. An append records the result. A change
    here gives a record that does not agree with its command.
    """
    try:
        parsed = parse_uuidv7(value)
    except UUIDv7ParseError as error:
        raise ValueError(f"{value!r} is not a UUIDv7: {error}") from error
    if str(parsed) != value:
        raise ValueError(
            f"{value!r} is not canonical UUIDv7 text; it would be recorded as "
            f"{str(parsed)!r}. A payload carries the form it will be read back "
            "in."
        )
    return value


#: Text, not `timetracker.uuidv7.UUIDv7`.
#: In strict mode, pydantic does not send text to a `uuid.UUID` schema.
#: JSONB also cannot store the `uuid.UUID` result.
type ReferenceId = Annotated[str, AfterValidator(canonical_uuid_text)]


@with_config(STRICT_SCHEMA)
class Reference(TypedDict):
    """One referenced row, as recorded."""

    kind: ReferenceKindName
    id: ReferenceId
    label: str
    detail: str


class Resolution(StrEnum):
    """Whether a replay must find the row."""

    REQUIRED = "required"
    EVIDENCE_ONLY = "evidence_only"


@dataclass(frozen=True, slots=True)
class ReferenceKind[M: models.Model]:
    """One referenced model and what events record."""

    name: ReferenceKindName
    model: type[M]
    capture: Callable[[M], Reference]
    resolution: Resolution


class ReferenceKindRegistry:
    """The kinds a payload may name."""

    def __init__(self) -> None:
        self._by_name: dict[ReferenceKindName, ReferenceKind[Any]] = {}
        self._by_model: dict[type[models.Model], ReferenceKind[Any]] = {}

    def register(self, kind: ReferenceKind[Any]) -> None:
        if not kind.name:
            raise ValueError(
                f"{kind.model.__name__} registers under an empty reference "
                "kind. The name is what a recorded payload is read back by."
            )
        claimed = self._by_name.get(kind.name)
        if claimed is not None:
            raise ValueError(
                f"{kind.name!r} is already registered, for "
                f"{claimed.model.__name__}. A kind names one model, or a "
                "recorded reference says nothing about where to look."
            )
        captured = self._by_model.get(kind.model)
        if captured is not None:
            raise ValueError(
                f"{kind.model.__name__} is already captured as "
                f"{captured.name!r}. One model has one kind, so capturing an "
                "instance never has to choose."
            )
        self._by_name[kind.name] = kind
        self._by_model[kind.model] = kind

    def kind_for(self, name: ReferenceKindName) -> ReferenceKind[Any]:
        try:
            return self._by_name[name]
        except KeyError:
            raise UnknownReferenceKind(
                f"{name!r} is not a registered reference kind. Every kind a "
                "payload names is a ReferenceKind registered here."
            ) from None

    def kind_of(self, instance: models.Model) -> ReferenceKind[Any]:
        try:
            return self._by_model[type(instance)]
        except KeyError:
            raise UnmappedReferenceModel(
                f"{type(instance).__name__} has no reference kind, so an event "
                "cannot record one of its rows. Register a ReferenceKind for "
                "it, deciding what its snapshot shows and whether a replay "
                "must resolve it."
            ) from None

    def capture(self, instance: models.Model) -> Reference:
        """The reference an event records for `instance`."""
        return self.kind_of(instance).capture(instance)

    def __contains__(self, name: ReferenceKindName) -> bool:
        return name in self._by_name

    def __iter__(self) -> Iterator[ReferenceKind[Any]]:
        """Every registered kind, for a caller checking coverage."""
        return iter(self._by_name.values())


def _capture_device(device: Device) -> Reference:
    return Reference(
        kind="device", id=str(device.pk), label=device.name, detail=device.type
    )


def _capture_game(game: Game) -> Reference:
    return Reference(
        kind="catalog.game",
        id=str(game.pk),
        label=game.name,
        detail="" if game.year_released is None else str(game.year_released),
    )


def _capture_platform(platform: Platform) -> Reference:
    return Reference(
        kind="catalog.platform",
        id=str(platform.pk),
        label=platform.name,
        detail=platform.group,
    )


def _capture_release(release: Release) -> Reference:
    """A Release has no words of its own.

    The label is the Game's name, thus a reader of a recorded
    reference sees the work. The detail is the Platform, which is
    what tells two Releases of one Game apart. Both are joins: a
    caller capturing many selects them first.
    """
    return Reference(
        kind="catalog.release",
        id=str(release.pk),
        label=release.edition.game.name,
        detail="" if release.platform is None else release.platform.name,
    )


#: The kinds an event may reference.
DEFAULT_REFERENCE_KINDS = ReferenceKindRegistry()
DEFAULT_REFERENCE_KINDS.register(
    ReferenceKind(
        name="device",
        model=Device,
        capture=_capture_device,
        resolution=Resolution.REQUIRED,
    )
)
DEFAULT_REFERENCE_KINDS.register(
    ReferenceKind(
        name="catalog.game",
        model=Game,
        capture=_capture_game,
        resolution=Resolution.REQUIRED,
    )
)
DEFAULT_REFERENCE_KINDS.register(
    ReferenceKind(
        name="catalog.platform",
        model=Platform,
        capture=_capture_platform,
        resolution=Resolution.REQUIRED,
    )
)
DEFAULT_REFERENCE_KINDS.register(
    ReferenceKind(
        name="catalog.release",
        model=Release,
        capture=_capture_release,
        resolution=Resolution.REQUIRED,
    )
)


def capture_reference(
    instance: models.Model, *, kinds: ReferenceKindRegistry = DEFAULT_REFERENCE_KINDS
) -> Reference:
    """Capture the reference a command records."""
    return kinds.capture(instance)


class ReferenceArity(StrEnum):
    """How many references one payload field holds."""

    SINGLE = "single"
    OPTIONAL = "optional"
    SEQUENCE = "sequence"


#: Which keys hold references, in what shape.
type ReferenceFields = Mapping[PayloadKey, ReferenceArity]


class FoundReference(NamedTuple):
    """One reference and the key holding it."""

    key: PayloadKey
    value: Reference


def _without_qualifiers(hint: Any) -> Any:
    """Strip wrappers that say nothing about shape."""
    while True:
        if get_origin(hint) in (Required, NotRequired):
            hint = get_args(hint)[0]
            continue
        if hasattr(hint, "__metadata__"):
            hint = get_args(hint)[0]
            continue
        return hint


def _mentions_reference(hint: Any, seen: frozenset[Any] = frozenset()) -> bool:
    """Whether a reference hides anywhere inside `hint`.

    Also examine a TypedDict in a field. `get_args` does not see into one.
    A reference there stays unknown to the replay check. `seen` stops a loop.
    """
    if hint is Reference:
        return True
    if is_typeddict(hint):
        if hint in seen:
            return False
        nested = get_type_hints(hint, include_extras=True).values()
        return any(_mentions_reference(field, seen | {hint}) for field in nested)
    return any(_mentions_reference(argument, seen) for argument in get_args(hint))


def _arity_of(hint: Any) -> ReferenceArity | None:
    """The arity `hint` declares, if any."""
    hint = _without_qualifiers(hint)
    if hint is Reference:
        return ReferenceArity.SINGLE
    origin = get_origin(hint)
    arguments = tuple(_without_qualifiers(argument) for argument in get_args(hint))
    if origin in (Union, types.UnionType) and set(arguments) == {
        Reference,
        types.NoneType,
    }:
        return ReferenceArity.OPTIONAL
    if origin is list and arguments == (Reference,):
        return ReferenceArity.SEQUENCE
    if _mentions_reference(hint):
        raise ReferenceFieldUnsupported(
            f"{hint!r} holds a reference somewhere nothing enumerates. A "
            "payload declares a reference as Reference, Reference | None, or "
            "list[Reference]; any other nesting is a reference a replay would "
            "never check."
        )
    return None


def reference_fields(payload: type) -> ReferenceFields:
    """Which of `payload`'s fields hold references."""
    found: dict[PayloadKey, ReferenceArity] = {}
    for key, hint in get_type_hints(payload, include_extras=True).items():
        arity = _arity_of(hint)
        if arity is not None:
            found[key] = arity
    return found


def references_in(
    payload: Mapping[str, Any], fields: ReferenceFields
) -> Iterator[FoundReference]:
    """Every reference `payload` carries at those fields."""
    for key, arity in fields.items():
        value = payload.get(key)
        if value is None:
            continue
        if arity is ReferenceArity.SEQUENCE:
            for item in value:
                yield FoundReference(key, item)
        else:
            yield FoundReference(key, value)


def check_kinds_registered(
    payload: Mapping[str, Any],
    fields: ReferenceFields,
    kinds: ReferenceKindRegistry = DEFAULT_REFERENCE_KINDS,
) -> None:
    """Refuse a payload naming an unregistered kind."""
    for key, value in references_in(payload, fields):
        name = value["kind"]
        if name not in kinds:
            raise UnknownReferenceKind(
                f"the reference at {key!r} names kind {name!r}, which is not "
                "registered. Every kind a payload names is a ReferenceKind."
            )
