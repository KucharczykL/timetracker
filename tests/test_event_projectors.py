"""The projector registry and its base class.

Every family here registers into a registry this module owns, so nothing
declared for a test can reach `DEFAULT_REGISTRY` or another test.
"""

import uuid
from datetime import UTC, datetime
from typing import Any, ClassVar, TypedDict

import pytest
from django.db import OperationalError, connection, transaction
from django.test.utils import CaptureQueriesContext
from pydantic import ConfigDict, with_config
from test_command_dispatch import COMMAND_RECORDED, BasicCommand
from test_event_retry import wrapped

from games.events.append import lock_stream
from games.events.dispatch import dispatch
from games.events.envelope import RecordedEvent
from games.events.idempotency import idempotent_append
from games.events.projection import (
    DEFAULT_REGISTRY,
    BoundHandler,
    HandlerMap,
    ProjectionRowMissing,
    Projector,
    ProjectorFamily,
    ProjectorRegistry,
)
from games.events.targets import LIVE_TARGET, ProjectionTarget
from games.events.vocabulary import EventSpec, EventTypeRegistry, NewEvent
from games.events.wiring import EventWiring
from games.models import (
    Device,
    LibraryEvent,
    LibraryEventStreamHead,
    ProjectionModel,
)

RECORDED = "test.projector.recorded"
OTHER = "test.projector.other"
UNHANDLED = "test.projector.unhandled"

#: What each handler saw, in the order it saw it.
CALLS: list[tuple[ProjectorFamily, str]] = []
#: The same, for the families the append path folds through: which family, and
#: which event of the append.
APPLIED: list[tuple[ProjectorFamily, int]] = []
#: The values those handlers were handed, kept whole so a test can read the
#: envelope a projector actually sees.
SEEN: list[RecordedEvent] = []
#: What the stream head said while a handler was running.
HEAD_SEQUENCE_SEEN: list[int] = []


@pytest.fixture
def second_library(django_user_model):
    return django_user_model.objects.create_user(
        username="second-owner", password="p"
    ).library


@pytest.fixture(autouse=True)
def forget_previous_calls():
    for sink in (CALLS, APPLIED, SEEN, HEAD_SEQUENCE_SEEN):
        sink.clear()
    yield
    for sink in (CALLS, APPLIED, SEEN, HEAD_SEQUENCE_SEEN):
        sink.clear()
    FlakyProjector.attempts = 0


def make_event(**overrides: Any) -> RecordedEvent:
    """An envelope nothing recorded: the registry reads it and touches no
    database.

    The defaults live here rather than on `RecordedEvent`, which has none: a
    partially-populated envelope is never wanted in production, and a default
    there would let the contract test pass over a field `from_row` forgot.
    """
    fields: dict[str, Any] = {
        "id": uuid.uuid7(),
        "library_id": uuid.uuid7(),
        "stream_id": uuid.uuid7(),
        "sequence": 1,
        "event_type": RECORDED,
        "aggregate_id": uuid.uuid7(),
        "payload_schema_version": 1,
        "recorded_at": datetime(2024, 5, 6, 7, 8, 9, tzinfo=UTC),
        "effective_time": None,
        "actor_id": None,
        "correlation_id": uuid.uuid7(),
        "causation_id": None,
        "source_metadata": {},
        "idempotency_key": "probe-key",
        "payload": {"probe": True},
    }
    fields.update(overrides)
    return RecordedEvent(**fields)


@with_config(ConfigDict(extra="forbid", strict=True))
class ProbePayload(TypedDict):
    probe: bool


PROBE_RECORDED = EventSpec(RECORDED, aggregate_type="probe", payload=ProbePayload)
PROBE_OTHER = EventSpec(OTHER, aggregate_type="probe", payload=ProbePayload)

#: This module's vocabulary, plus the dispatch specs.
EVENT_TYPES = EventTypeRegistry()
for spec in (PROBE_RECORDED, PROBE_OTHER, COMMAND_RECORDED):
    EVENT_TYPES.register(spec)


ordering_registry = ProjectorRegistry()


#: Declared before the current-state family and expected to run after it. The
#: order is the enum's, not the order classes happen to be imported in.
class JournalRecorder(Projector, registry=ordering_registry):
    family_name = ProjectorFamily.JOURNAL

    def _recorded(self, event: RecordedEvent) -> None:
        CALLS.append((ProjectorFamily.JOURNAL, event.event_type))

    handles: ClassVar[HandlerMap] = {PROBE_RECORDED: _recorded}


class CurrentStateRecorder(Projector, registry=ordering_registry):
    family_name = ProjectorFamily.CURRENT_STATE

    def _recorded(self, event: RecordedEvent) -> None:
        CALLS.append((ProjectorFamily.CURRENT_STATE, event.event_type))

    def _other(self, event: RecordedEvent) -> None:
        CALLS.append((ProjectorFamily.CURRENT_STATE, event.event_type))

    handles: ClassVar[HandlerMap] = {PROBE_RECORDED: _recorded, PROBE_OTHER: _other}


def test_a_family_must_name_itself():
    with pytest.raises(TypeError, match="declares no family_name"):

        class Nameless(Projector, registry=ProjectorRegistry()):
            handles: ClassVar[HandlerMap] = {}


def test_a_family_must_declare_what_it_handles():
    with pytest.raises(TypeError, match="declares no handles"):

        class Handleless(Projector, registry=ProjectorRegistry()):
            family_name = ProjectorFamily.STATS


def test_an_abstract_base_need_not_declare_either():
    class Base(Projector, abstract=True):
        pass

    assert not hasattr(Base, "family_name")


def test_a_handler_must_be_callable():
    with pytest.raises(TypeError, match="not callable"):

        class Mistyped(Projector, registry=ProjectorRegistry()):
            family_name = ProjectorFamily.STATS
            handles: ClassVar[HandlerMap] = {PROBE_RECORDED: "recorded"}


def test_a_family_cannot_claim_a_bare_event_type_string():
    """A string names no event type."""
    with pytest.raises(TypeError, match="not an EventSpec"):

        class Stringly(Projector, registry=ProjectorRegistry()):
            family_name = ProjectorFamily.STATS

            def _recorded(self, event: RecordedEvent) -> None: ...

            handles: ClassVar[HandlerMap] = {RECORDED: _recorded}


def test_a_family_is_dispatched_for_the_event_type_its_spec_names():
    registry = ProjectorRegistry()

    class SpecKeyed(Projector, registry=registry):
        family_name = ProjectorFamily.STATS

        def _recorded(self, event: RecordedEvent) -> None:
            CALLS.append((ProjectorFamily.STATS, event.event_type))

        handles: ClassVar[HandlerMap] = {PROBE_RECORDED: _recorded}

    #: The lookup key is a string.
    assert len(registry.handlers_for(RECORDED)) == 1

    registry.apply(make_event())

    assert CALLS == [(ProjectorFamily.STATS, RECORDED)]


def test_two_families_cannot_claim_one_member():
    registry = ProjectorRegistry()

    class First(Projector, registry=registry):
        family_name = ProjectorFamily.STATS

        def _recorded(self, event: RecordedEvent) -> None: ...

        handles: ClassVar[HandlerMap] = {PROBE_RECORDED: _recorded}

    with pytest.raises(TypeError, match="already owned by"):

        class Second(Projector, registry=registry):
            family_name = ProjectorFamily.STATS

            def _recorded(self, event: RecordedEvent) -> None: ...

            handles: ClassVar[HandlerMap] = {PROBE_RECORDED: _recorded}


def test_registering_one_family_twice_is_not_a_collision():
    registry = ProjectorRegistry()

    class Once(Projector, registry=registry):
        family_name = ProjectorFamily.STATS

        def _recorded(self, event: RecordedEvent) -> None:
            CALLS.append((ProjectorFamily.STATS, event.event_type))

        handles: ClassVar[HandlerMap] = {PROBE_RECORDED: _recorded}

    registry.register(Once)

    #: Re-registering replaces the family rather than adding a second copy of it.
    registry.apply(make_event())
    assert CALLS == [(ProjectorFamily.STATS, RECORDED)]


def test_a_test_registry_leaves_the_default_one_empty():
    assert DEFAULT_REGISTRY.handlers_for(RECORDED) == ()
    assert DEFAULT_REGISTRY.handlers_for(OTHER) == ()


def test_families_run_in_member_order_not_registration_order():
    ordering_registry.apply(make_event())

    assert CALLS == [
        (ProjectorFamily.CURRENT_STATE, RECORDED),
        (ProjectorFamily.JOURNAL, RECORDED),
    ]


def test_a_family_handles_only_the_types_it_declares():
    ordering_registry.apply(make_event(event_type=OTHER))

    assert CALLS == [(ProjectorFamily.CURRENT_STATE, OTHER)]


def test_an_unhandled_event_type_runs_nothing():
    assert ordering_registry.handlers_for(UNHANDLED) == ()

    ordering_registry.apply(make_event(event_type=UNHANDLED))

    assert CALLS == []


def test_a_handler_is_bound_to_its_family():
    handler = ordering_registry.handlers_for(RECORDED)[0]

    assert handler.__self__.family_name is ProjectorFamily.CURRENT_STATE


class RecordingTarget:
    """Hands back the live model, remembers asking."""

    def __init__(self) -> None:
        self.asked: list[str] = []

    def model[M: ProjectionModel](self, model: type[M]) -> type[M]:
        self.asked.append(model.__name__)
        return model


def family_behind(handler: BoundHandler) -> Projector:
    """The family a bound handler came from."""
    return handler.__self__  # type: ignore[attr-defined]


def targets_of(registry: ProjectorRegistry) -> list[ProjectionTarget]:
    return [
        family_behind(handler).target for handler in registry.handlers_for(RECORDED)
    ]


def families_of(registry: ProjectorRegistry) -> list[ProjectorFamily]:
    return [
        family_behind(handler).family_name
        for handler in registry.handlers_for(RECORDED)
    ]


def test_a_family_holds_the_live_target_by_default():
    assert targets_of(ordering_registry) == [LIVE_TARGET, LIVE_TARGET]


def test_a_sibling_registry_points_every_family_at_the_given_target():
    shadow = RecordingTarget()

    sibling = ordering_registry.for_target(shadow)

    assert targets_of(sibling) == [shadow, shadow]
    #: The registry it came from is untouched.
    assert targets_of(ordering_registry) == [LIVE_TARGET, LIVE_TARGET]


def test_a_sibling_registry_resolves_the_same_families_in_the_same_order():
    sibling = ordering_registry.for_target(RecordingTarget())

    assert families_of(sibling) == families_of(ordering_registry)
    assert families_of(sibling) == [
        ProjectorFamily.CURRENT_STATE,
        ProjectorFamily.JOURNAL,
    ]


def test_a_sibling_registry_rebuilds_rather_than_re_registers():
    """`for_target` cannot route through `register`."""
    shadow = RecordingTarget()

    first = ordering_registry.for_target(shadow)
    second = ordering_registry.for_target(shadow)

    assert families_of(first) == families_of(second)
    assert targets_of(second) == [shadow, shadow]


def test_registering_a_family_against_a_target_hands_it_that_target():
    registry = ProjectorRegistry()

    class Direct(Projector, registry=registry):
        family_name = ProjectorFamily.STATS

        def _recorded(self, event: RecordedEvent) -> None: ...

        handles: ClassVar[HandlerMap] = {PROBE_RECORDED: _recorded}

    target = RecordingTarget()
    registry.register(Direct, target=target)

    assert targets_of(registry) == [target]


target_registry = ProjectorRegistry()


class TargetedWriter(Projector, registry=target_registry):
    """Writes wherever its target points."""

    family_name = ProjectorFamily.CURRENT_STATE

    def _recorded(self, event: RecordedEvent) -> None:
        #: Device stands in for a projection table.
        projected = self.target.model(Device)  # type: ignore[type-var]
        projected.objects.create(library_id=event.library_id, name="projected")

    handles: ClassVar[HandlerMap] = {PROBE_RECORDED: _recorded}


@pytest.mark.django_db
def test_a_handler_writes_through_the_target_its_family_holds(owned_library):
    target = RecordingTarget()

    target_registry.for_target(target).apply(make_event(library_id=owned_library.pk))

    assert target.asked == ["Device"]
    assert Device.objects.filter(name="projected").count() == 1


project_registry = ProjectorRegistry()


class ProjectingWriter(Projector, registry=project_registry):
    """Writes its whole row through the helper."""

    family_name = ProjectorFamily.CURRENT_STATE

    def _recorded(self, event: RecordedEvent) -> None:
        #: Device stands in for a projection table.
        self.project(  # type: ignore[type-var]
            Device,
            event.aggregate_id,
            library_id=event.library_id,
            name=f"projected {event.sequence}",
            type=Device.UNKNOWN,
        )

    handles: ClassVar[HandlerMap] = {PROBE_RECORDED: _recorded}


@pytest.mark.django_db
def test_the_helper_writes_through_the_target_its_family_holds(owned_library):
    target = RecordingTarget()

    project_registry.for_target(target).apply(make_event(library_id=owned_library.pk))

    assert target.asked == ["Device"]
    assert Device.objects.filter(name="projected 1").count() == 1


@pytest.mark.django_db
def test_the_helper_writes_one_row_through_one_statement(owned_library):
    """Five removed statements were a lock-and-look."""
    with CaptureQueriesContext(connection) as queries:
        project_registry.apply(make_event(library_id=owned_library.pk))

    assert len(queries) == 1
    assert queries[0]["sql"].startswith("INSERT INTO")
    assert "ON CONFLICT" in queries[0]["sql"]


@pytest.mark.django_db
def test_the_helper_rewrites_the_row_an_identity_already_has(owned_library):
    """A re-fold upserts; it adds no row."""
    identity = uuid.uuid7()

    for sequence in (1, 2):
        project_registry.apply(
            make_event(
                library_id=owned_library.pk,
                aggregate_id=identity,
                sequence=sequence,
            )
        )

    assert Device.objects.count() == 1
    assert Device.objects.get(pk=identity).name == "projected 2"


@pytest.mark.django_db
def test_the_helper_keeps_the_columns_it_was_not_given(owned_library):
    """DO UPDATE writes the named columns only."""
    identity = uuid.uuid7()
    project_registry.apply(
        make_event(library_id=owned_library.pk, aggregate_id=identity)
    )
    created_at = Device.objects.get(pk=identity).created_at

    project_registry.apply(
        make_event(library_id=owned_library.pk, aggregate_id=identity, sequence=2)
    )

    assert Device.objects.get(pk=identity).created_at == created_at


@pytest.mark.django_db
def test_the_helper_lets_the_database_fill_what_it_can(owned_library):
    """created_at fills itself, so a fold need not name it."""
    project_registry.apply(make_event(library_id=owned_library.pk))

    assert Device.objects.get().created_at is not None


partial_registry = ProjectorRegistry()


class PartialWriter(Projector, registry=partial_registry):
    """Leaves a column nothing else will fill."""

    family_name = ProjectorFamily.CURRENT_STATE

    def _recorded(self, event: RecordedEvent) -> None:
        #: Device stands in for a projection table.
        self.project(  # type: ignore[type-var]
            Device,
            event.aggregate_id,
            library_id=event.library_id,
        )

    handles: ClassVar[HandlerMap] = {PROBE_RECORDED: _recorded}


@pytest.mark.django_db
def test_the_helper_refuses_a_row_it_was_not_given_whole(owned_library):
    """A rebuild would null what the live path kept."""
    with pytest.raises(TypeError, match="folded without name"):
        partial_registry.apply(make_event(library_id=owned_library.pk))

    assert Device.objects.count() == 0


amend_registry = ProjectorRegistry()


class AmendingWriter(Projector, registry=amend_registry):
    """Changes one column of a row that exists."""

    family_name = ProjectorFamily.CURRENT_STATE

    def _recorded(self, event: RecordedEvent) -> None:
        #: Device stands in for a projection table.
        self.amend(  # type: ignore[type-var]
            Device,
            event.aggregate_id,
            name=f"amended {event.sequence}",
        )

    handles: ClassVar[HandlerMap] = {PROBE_RECORDED: _recorded}


def created_row(library, identity: uuid.UUID) -> Device:
    """The row a creation event would have folded."""
    return Device.objects.create(
        pk=identity, library_id=library.pk, name="created", type=Device.UNKNOWN
    )


@pytest.mark.django_db
def test_an_amendment_changes_the_columns_it_names(owned_library):
    identity = uuid.uuid7()
    created_row(owned_library, identity)

    amend_registry.apply(make_event(library_id=owned_library.pk, aggregate_id=identity))

    row = Device.objects.get(pk=identity)
    assert (row.name, row.type) == ("amended 1", Device.UNKNOWN)


@pytest.mark.django_db
def test_an_amendment_costs_one_statement(owned_library):
    """One UPDATE, and no read to build it."""
    identity = uuid.uuid7()
    created_row(owned_library, identity)

    with CaptureQueriesContext(connection) as queries:
        amend_registry.apply(
            make_event(library_id=owned_library.pk, aggregate_id=identity)
        )

    assert [query["sql"].split(maxsplit=1)[0] for query in queries] == ["UPDATE"]


@pytest.mark.django_db
def test_an_amendment_writes_through_the_target_its_family_holds(owned_library):
    identity = uuid.uuid7()
    created_row(owned_library, identity)
    target = RecordingTarget()

    amend_registry.for_target(target).apply(
        make_event(library_id=owned_library.pk, aggregate_id=identity)
    )

    assert target.asked == ["Device"]
    assert Device.objects.get(pk=identity).name == "amended 1"


@pytest.mark.django_db
def test_an_amendment_with_no_row_is_refused(owned_library):
    """Out of order, or a stream missing its creation event."""
    with pytest.raises(ProjectionRowMissing, match="no row"):
        amend_registry.apply(make_event(library_id=owned_library.pk))

    assert Device.objects.count() == 0


def wiring_over(projectors: ProjectorRegistry) -> EventWiring:
    """This module's wiring over the given families."""
    return EventWiring(projectors=projectors, event_types=EVENT_TYPES)


def make_new_event() -> NewEvent:
    return PROBE_RECORDED.new(aggregate_id=uuid.uuid7(), payload={"probe": True})


append_registry = ProjectorRegistry()
append_wiring = wiring_over(append_registry)


class AppendCurrentState(Projector, registry=append_registry):
    family_name = ProjectorFamily.CURRENT_STATE

    def _recorded(self, event: RecordedEvent) -> None:
        APPLIED.append((ProjectorFamily.CURRENT_STATE, event.sequence))
        SEEN.append(event)
        HEAD_SEQUENCE_SEEN.append(
            LibraryEventStreamHead.objects.get(pk=event.stream_id).current_sequence
        )

    handles: ClassVar[HandlerMap] = {PROBE_RECORDED: _recorded}


class AppendJournal(Projector, registry=append_registry):
    family_name = ProjectorFamily.JOURNAL

    def _recorded(self, event: RecordedEvent) -> None:
        APPLIED.append((ProjectorFamily.JOURNAL, event.sequence))

    handles: ClassVar[HandlerMap] = {PROBE_RECORDED: _recorded}


rollback_registry = ProjectorRegistry()
rollback_wiring = wiring_over(rollback_registry)


class RollbackWriter(Projector, registry=rollback_registry):
    family_name = ProjectorFamily.CURRENT_STATE

    def _recorded(self, event: RecordedEvent) -> None:
        Device.objects.create(library_id=event.library_id, name="projected")

    handles: ClassVar[HandlerMap] = {PROBE_RECORDED: _recorded}


class RollbackFailer(Projector, registry=rollback_registry):
    family_name = ProjectorFamily.STATS

    def _recorded(self, event: RecordedEvent) -> None:
        raise RuntimeError("the stats family refused")

    handles: ClassVar[HandlerMap] = {PROBE_RECORDED: _recorded}


dispatch_registry = ProjectorRegistry()
dispatch_wiring = wiring_over(dispatch_registry)


class DispatchRecorder(Projector, registry=dispatch_registry):
    family_name = ProjectorFamily.CURRENT_STATE

    def _recorded(self, event: RecordedEvent) -> None:
        APPLIED.append((ProjectorFamily.CURRENT_STATE, event.sequence))

    handles: ClassVar[HandlerMap] = {COMMAND_RECORDED: _recorded}


quiet_registry = ProjectorRegistry()
quiet_wiring = wiring_over(quiet_registry)


class QuietRecorder(Projector, registry=quiet_registry):
    """Reads the envelope and nothing else, so every query the append issues
    while it is folding is the append's own."""

    family_name = ProjectorFamily.CURRENT_STATE

    def _recorded(self, event: RecordedEvent) -> None:
        APPLIED.append((ProjectorFamily.CURRENT_STATE, event.sequence))

    handles: ClassVar[HandlerMap] = {PROBE_RECORDED: _recorded}


actor_registry = ProjectorRegistry()
actor_wiring = wiring_over(actor_registry)


class ActorReader(Projector, registry=actor_registry):
    family_name = ProjectorFamily.CURRENT_STATE

    def _recorded(self, event: RecordedEvent) -> None:
        #: The traversal this issue exists to prevent. mypy refuses it too --
        #: the ignore is what makes the runtime refusal worth asserting.
        actor = event.actor  # type: ignore[attr-defined]
        CALLS.append((ProjectorFamily.CURRENT_STATE, str(actor)))

    handles: ClassVar[HandlerMap] = {PROBE_RECORDED: _recorded}


retry_registry = ProjectorRegistry()
retry_wiring = wiring_over(retry_registry)


class FlakyProjector(Projector, registry=retry_registry):
    """Fails its first attempt the way PostgreSQL kills a deadlocked one.

    The attempt counter is neither a field nor a row, so it survives the
    rollback the retry depends on -- the same test-only violation of
    `run_in_transaction`'s "no effects outside the database" contract that
    `FlakyCommand` already makes.
    """

    family_name = ProjectorFamily.CURRENT_STATE
    attempts: ClassVar[int] = 0

    def _recorded(self, event: RecordedEvent) -> None:
        type(self).attempts += 1
        if type(self).attempts == 1:
            raise wrapped(OperationalError, "40P01")
        APPLIED.append((ProjectorFamily.CURRENT_STATE, event.sequence))

    handles: ClassVar[HandlerMap] = {COMMAND_RECORDED: _recorded}


def append(library, wiring, count: int = 1, idempotency_key: str = "probe-key"):
    return lock_stream(library).append(
        [make_new_event() for _ in range(count)],
        actor=None,
        correlation_id=uuid.uuid7(),
        idempotency_key=idempotency_key,
        wiring=wiring,
    )


@pytest.mark.django_db
def test_an_append_folds_one_event_at_a_time_through_every_family(owned_library):
    with transaction.atomic():
        append(owned_library, append_wiring, count=2)

    #: Event-major: one event through the whole pipeline, then the next. The
    #: append path and a replay fold identically only in this order.
    assert APPLIED == [
        (ProjectorFamily.CURRENT_STATE, 1),
        (ProjectorFamily.JOURNAL, 1),
        (ProjectorFamily.CURRENT_STATE, 2),
        (ProjectorFamily.JOURNAL, 2),
    ]


@pytest.mark.django_db
def test_a_handler_receives_the_recorded_event(owned_library):
    correlation_id = uuid.uuid7()

    with transaction.atomic():
        result = lock_stream(owned_library).append(
            [make_new_event()],
            actor=None,
            correlation_id=correlation_id,
            idempotency_key="probe-key",
            wiring=append_wiring,
        )

    projected = SEEN[0]
    assert projected.id == result.events[0].pk
    assert projected.sequence == 1
    assert projected.library_id == owned_library.pk
    assert projected.correlation_id == correlation_id
    assert projected.payload == {"probe": True}


@pytest.mark.django_db
def test_the_head_has_advanced_before_any_handler_runs(owned_library):
    with transaction.atomic():
        append(owned_library, append_wiring, count=2)

    #: Both handlers see the whole append already recorded, not the event they
    #: happen to be holding.
    assert HEAD_SEQUENCE_SEEN == [2, 2]


@pytest.mark.django_db
def test_a_replayed_append_folds_nothing(owned_library):
    def build(stream):
        return [make_new_event()]

    for _ in range(2):
        with transaction.atomic():
            idempotent_append(
                owned_library,
                idempotency_key="once",
                command_input={"probe": True},
                build=build,
                actor=None,
                correlation_id=uuid.uuid7(),
                wiring=append_wiring,
            )

    assert APPLIED == [
        (ProjectorFamily.CURRENT_STATE, 1),
        (ProjectorFamily.JOURNAL, 1),
    ]
    assert LibraryEvent.objects.count() == 1


@pytest.mark.django_db
def test_a_failing_family_takes_an_earlier_familys_write_with_it(owned_library):
    with (
        pytest.raises(RuntimeError, match="stats family refused"),
        transaction.atomic(),
    ):
        append(owned_library, rollback_wiring)

    assert not Device.objects.exists()
    assert not LibraryEvent.objects.exists()
    assert not LibraryEventStreamHead.objects.filter(current_sequence__gt=0).exists()


@pytest.mark.django_db(transaction=True)
def test_dispatch_folds_through_the_registry_it_was_given(owned_user, owned_library):
    dispatch(
        BasicCommand(label="first", count=1),
        actor=owned_user,
        library=owned_library,
        idempotency_key="dispatched",
        wiring=dispatch_wiring,
    )

    assert APPLIED == [(ProjectorFamily.CURRENT_STATE, 1)]


@pytest.mark.django_db
def test_a_failing_handler_names_itself_without_being_wrapped(owned_library):
    with pytest.raises(RuntimeError) as raised, transaction.atomic():
        append(owned_library, rollback_wiring)

    #: Exactly RuntimeError, not a subclass and not something carrying it: the
    #: retry classifier reads the type, so a wrapper would be invisible to it.
    assert type(raised.value) is RuntimeError
    note = "\n".join(raised.value.__notes__)
    assert ProjectorFamily.STATS.value in note
    assert RECORDED in note
    assert "#1" in note


@pytest.mark.django_db(transaction=True)
def test_a_retryable_failure_inside_a_handler_is_still_retried(
    owned_user, owned_library
):
    """The load-bearing test for the error contract.

    Wrapping a projector's exception in a `ProjectionFailed` would satisfy
    neither of `run_in_transaction`'s checks -- the type nor the chained
    SQLSTATE -- so every projected command would silently stop being retried.
    This is what fails if anyone does it.
    """
    dispatch(
        BasicCommand(label="flaky", count=1),
        actor=owned_user,
        library=owned_library,
        idempotency_key="flaky",
        wiring=retry_wiring,
    )

    assert FlakyProjector.attempts == 2
    assert APPLIED == [(ProjectorFamily.CURRENT_STATE, 1)]
    assert LibraryEvent.objects.count() == 1


@pytest.mark.django_db
def test_a_handler_cannot_traverse_to_the_actor(owned_library):
    with pytest.raises(AttributeError) as raised, transaction.atomic():
        append(owned_library, actor_wiring)

    assert "actor" in str(raised.value)


@pytest.mark.django_db
def test_folding_costs_the_append_no_query(owned_library, second_library):
    """What the value type buys, as an assertion.

    A family reading the envelope adds nothing to the append, because there is
    nothing left on the event to make it fetch.
    """
    with transaction.atomic(), CaptureQueriesContext(connection) as unprojected:
        append(owned_library, wiring_over(ProjectorRegistry()), count=3)
    with transaction.atomic(), CaptureQueriesContext(connection) as projected:
        append(second_library, quiet_wiring, count=3)

    assert APPLIED == [
        (ProjectorFamily.CURRENT_STATE, sequence) for sequence in (1, 2, 3)
    ]
    assert len(projected) == len(unprojected)
