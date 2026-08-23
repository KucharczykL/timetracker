"""The projector registry and its base class.

Every family here registers into a registry this module owns, so nothing
declared for a test can reach `DEFAULT_REGISTRY` or another test.
"""

from typing import ClassVar

import pytest

from games.events.projection import (
    DEFAULT_REGISTRY,
    HandlerMap,
    Projector,
    ProjectorFamily,
    ProjectorRegistry,
)
from games.models import LibraryEvent

RECORDED = "test.projector.recorded"
OTHER = "test.projector.other"
UNHANDLED = "test.projector.unhandled"

#: What each handler saw, in the order it saw it.
CALLS: list[tuple[ProjectorFamily, str]] = []


@pytest.fixture(autouse=True)
def forget_previous_calls():
    CALLS.clear()
    yield
    CALLS.clear()


def make_event(event_type: str = RECORDED, sequence: int = 1) -> LibraryEvent:
    """An unsaved row: the registry reads the envelope and touches no database."""
    return LibraryEvent(event_type=event_type, sequence=sequence)


ordering_registry = ProjectorRegistry()


#: Declared before the current-state family and expected to run after it. The
#: order is the enum's, not the order classes happen to be imported in.
class JournalRecorder(Projector, registry=ordering_registry):
    family_name = ProjectorFamily.JOURNAL

    def _recorded(self, event: LibraryEvent) -> None:
        CALLS.append((ProjectorFamily.JOURNAL, event.event_type))

    handles: ClassVar[HandlerMap] = {RECORDED: _recorded}


class CurrentStateRecorder(Projector, registry=ordering_registry):
    family_name = ProjectorFamily.CURRENT_STATE

    def _recorded(self, event: LibraryEvent) -> None:
        CALLS.append((ProjectorFamily.CURRENT_STATE, event.event_type))

    def _other(self, event: LibraryEvent) -> None:
        CALLS.append((ProjectorFamily.CURRENT_STATE, event.event_type))

    handles: ClassVar[HandlerMap] = {RECORDED: _recorded, OTHER: _other}


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
            handles: ClassVar[HandlerMap] = {RECORDED: "recorded"}


def test_two_families_cannot_claim_one_member():
    registry = ProjectorRegistry()

    class First(Projector, registry=registry):
        family_name = ProjectorFamily.STATS

        def _recorded(self, event: LibraryEvent) -> None: ...

        handles: ClassVar[HandlerMap] = {RECORDED: _recorded}

    with pytest.raises(TypeError, match="already owned by"):

        class Second(Projector, registry=registry):
            family_name = ProjectorFamily.STATS

            def _recorded(self, event: LibraryEvent) -> None: ...

            handles: ClassVar[HandlerMap] = {RECORDED: _recorded}


def test_registering_one_family_twice_is_not_a_collision():
    registry = ProjectorRegistry()

    class Once(Projector, registry=registry):
        family_name = ProjectorFamily.STATS

        def _recorded(self, event: LibraryEvent) -> None:
            CALLS.append((ProjectorFamily.STATS, event.event_type))

        handles: ClassVar[HandlerMap] = {RECORDED: _recorded}

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
    ordering_registry.apply(make_event(OTHER))

    assert CALLS == [(ProjectorFamily.CURRENT_STATE, OTHER)]


def test_an_unhandled_event_type_runs_nothing():
    assert ordering_registry.handlers_for(UNHANDLED) == ()

    ordering_registry.apply(make_event(UNHANDLED))

    assert CALLS == []


def test_a_handler_is_bound_to_its_family():
    handler = ordering_registry.handlers_for(RECORDED)[0]

    assert handler.__self__.family_name is ProjectorFamily.CURRENT_STATE
