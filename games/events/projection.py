"""Which projection families exist, in what order they run, and what each one
does with an event.

A family is one class owning one projection concern. It declares the event types
it handles as a mapping keyed on their `EventSpec` constants, and the append path
folds every appended event through every family that claims its type -- in the
same transaction, under the same stream-head lock.

A family is handed a `RecordedEvent`, never the row, so nothing here holds a
model: a registry of families over a value. That is what lets `for_target`
return the same families pointed at tables other than the live ones, which is
how a rebuild replays a stream without the application seeing it.

The module is `projection` rather than `projectors` because `games.projectors`
is the package the real families live in. Two importable modules of one name are
unambiguous to the interpreter and a trap for everyone else.
"""

from abc import ABC
from collections.abc import Callable, Mapping
from enum import StrEnum
from typing import Any, ClassVar

from games.events.envelope import RecordedEvent
from games.events.targets import LIVE_TARGET, ProjectionTarget
from games.events.vocabulary import EventSpec, EventType

type BoundHandler = Callable[[RecordedEvent], None]
#: EventSpec keys; values are the handler functions, read out of the class body
#: before any descriptor binding -- hence Callable[..., None] rather than a
#: signature naming `self`.
type HandlerMap = Mapping[EventSpec[Any], Callable[..., None]]
#: One handler and the family it speaks for, so a failure can say which.
type FamilyHandler = tuple[ProjectorFamily, BoundHandler]
#: Where a family was defined, as (module, qualified name).
type DefinitionSite = tuple[str, str]  # ("games.projectors.journal", "Journal")


class ProjectorFamily(StrEnum):
    """Every projection family, in the order they run within one event.

    **Member order is run order.** Journal and statistics families read the
    current-state rows written earlier in the same transaction, so the order is
    load-bearing and must not depend on which module Python imported first.

    Nothing persists these names -- they are an ordering key, not the audit
    trail's vocabulary -- so a member may be renamed, added, or reordered
    without invalidating anything already recorded.
    """

    CURRENT_STATE = "current_state"
    JOURNAL = "journal"
    STATS = "stats"


#: Resolved once: the enum's own member order, as a sort key.
_RUN_ORDER: dict[ProjectorFamily, int] = {
    family: position for position, family in enumerate(ProjectorFamily)
}


class ProjectorRegistry:
    """The families that run, and the handlers each event type resolves to.

    An object rather than a module-level dict so a caller can hold one of its
    own: a test registers into a registry nobody else sees, and a rebuild can
    eventually assemble a set of families pointed somewhere other than the live
    tables.
    """

    def __init__(self) -> None:
        self._families: dict[ProjectorFamily, Projector] = {}
        #: Kept so `for_target` can build a sibling from the classes rather
        #: than from the instances, which hold a target already.
        self._classes: dict[ProjectorFamily, type[Projector]] = {}
        self._claims: dict[ProjectorFamily, DefinitionSite] = {}
        #: The string a RecordedEvent carries.
        self._handlers: dict[EventType, tuple[FamilyHandler, ...]] = {}

    def register(
        self,
        projector_class: type[Projector],
        *,
        target: ProjectionTarget = LIVE_TARGET,
    ) -> None:
        family_name = getattr(projector_class, "family_name", None)
        if not isinstance(family_name, ProjectorFamily):
            raise TypeError(
                f"{projector_class.__qualname__} declares no family_name. Every "
                "concrete family names itself with a ProjectorFamily member."
            )

        handles = getattr(projector_class, "handles", None)
        if not isinstance(handles, Mapping):
            raise TypeError(
                f"{projector_class.__qualname__} declares no handles. A family "
                "says which event types it projects, even if that is none."
            )
        for spec, handler in handles.items():
            if not isinstance(spec, EventSpec):
                raise TypeError(
                    f"{projector_class.__qualname__} claims {spec!r}, which is "
                    "not an EventSpec. A family names the specs it handles, so "
                    "it cannot claim an event type nobody defined."
                )
            if not callable(handler):
                raise TypeError(
                    f"{projector_class.__qualname__} maps {spec.event_type!r} to "
                    f"{handler!r}, which is not callable. Handlers are the "
                    "functions themselves, so renaming one is an error here "
                    "rather than a handler that never runs."
                )

        definition_site = (projector_class.__module__, projector_class.__qualname__)
        claimed_by = self._claims.get(family_name)
        if claimed_by is not None and claimed_by != definition_site:
            raise TypeError(
                f"{projector_class.__qualname__} claims {family_name.value!r}, "
                f"already owned by {claimed_by[0]}.{claimed_by[1]}."
            )

        #: At registration, therefore at import: a family takes its target and
        #: does no other work in __init__.
        self._families[family_name] = projector_class(target)
        self._classes[family_name] = projector_class
        self._claims[family_name] = definition_site
        self._rebuild_handlers()

    def for_target(self, target: ProjectionTarget) -> ProjectorRegistry:
        """The same families again, writing wherever `target` points.

        Built from the kept classes rather than routed back through
        `register`, which would refuse them: the duplicate-claim guard sees the
        same family claimed by the same site a second time. Instantiating here
        is also the only place the target reaches a family, so a sibling built
        by any other route would hold live-pointed families -- a rebuild
        quietly writing production.
        """
        sibling = ProjectorRegistry()
        sibling._classes = dict(self._classes)
        sibling._claims = dict(self._claims)
        sibling._families = {
            family_name: projector_class(target)
            for family_name, projector_class in self._classes.items()
        }
        sibling._rebuild_handlers()
        return sibling

    def _rebuild_handlers(self) -> None:
        handlers: dict[EventType, list[FamilyHandler]] = {}
        for family_name in sorted(self._families, key=_RUN_ORDER.__getitem__):
            family = self._families[family_name]
            for spec, handler in family.handles.items():
                handlers.setdefault(spec.event_type, []).append(
                    (family_name, handler.__get__(family))
                )
        self._handlers = {
            event_type: tuple(found) for event_type, found in handlers.items()
        }

    def handlers_for(self, event_type: EventType) -> tuple[BoundHandler, ...]:
        return tuple(handler for _, handler in self._handlers.get(event_type, ()))

    def apply(self, event: RecordedEvent) -> None:
        """Project one event through every family that claims its type.

        A handler's exception is annotated and re-raised, never wrapped and
        never caught: `run_in_transaction` decides whether to retry from the
        exception's type and its chained SQLSTATE, so a `ProjectionFailed`
        carrying the original would stop a serialization failure inside a
        projector from ever being retried. `add_note` adds the one fact a
        traceback is missing -- which family, on which event -- and changes
        nothing a caller can read.
        """
        for family_name, handler in self._handlers.get(event.event_type, ()):
            try:
                handler(event)
            except Exception as error:
                error.add_note(
                    f"raised by the {family_name.value} projector applying "
                    f"{event.event_type} #{event.sequence}"
                )
                raise


DEFAULT_REGISTRY = ProjectorRegistry()


class Projector(ABC):
    """One projection family.

    Subclassing registers, which is why `handles` maps `EventSpec` constants to
    the handler **functions** read out of the class body rather than strings to
    handler names: renaming either without updating the map is a `NameError` at
    class definition, where a string would have been a handler that silently
    never ran.

    A family spells the declaration `handles: ClassVar[HandlerMap] = {...}`. The
    annotation is not decoration: a bare assignment is a mutable class attribute
    that no type checker reads and that ruff refuses (RUF012).

    Instances are built once, at registration, with one argument: where they
    write. A family never imports its projection model -- it writes
    `self.target.model(Shelf).objects...`, and reads its own projections the
    same way, so a rebuild redirects it by handing it a different target.
    """

    family_name: ClassVar[ProjectorFamily]
    handles: ClassVar[HandlerMap]

    def __init__(self, target: ProjectionTarget = LIVE_TARGET) -> None:
        self.target = target

    def __init_subclass__(
        cls,
        *,
        abstract: bool = False,
        registry: ProjectorRegistry = DEFAULT_REGISTRY,
        **kwargs: object,
    ) -> None:
        super().__init_subclass__(**kwargs)
        #: Declared rather than detected: a family overrides no abstract method,
        #: so inspect.isabstract sees every intermediate base as concrete.
        if abstract:
            return
        registry.register(cls)
