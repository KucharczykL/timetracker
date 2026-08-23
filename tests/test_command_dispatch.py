import uuid
from collections.abc import Sequence
from dataclasses import dataclass, fields
from typing import ClassVar

import pytest

from games.events.append import NewEvent
from games.events.dispatch import Command, CommandContext, CommandName


@dataclass(frozen=True, slots=True)
class BasicCommand(Command):
    command_name: ClassVar[CommandName] = CommandName.TEST_KERNEL_BASIC
    label: str
    count: int

    def build(self, context: CommandContext) -> Sequence[NewEvent]:
        return [
            NewEvent(
                event_type="test.kernel.recorded",
                aggregate_type="test",
                aggregate_id=uuid.uuid7(),
                payload={"label": self.label, "count": self.count},
            )
        ]


@dataclass(frozen=True, slots=True)
class TwinCommand(Command):
    """BasicCommand's fields exactly, under another name, so a shared key can
    be shown to be refused on the name alone."""

    command_name: ClassVar[CommandName] = CommandName.TEST_KERNEL_TWIN
    label: str
    count: int

    def build(self, context: CommandContext) -> Sequence[NewEvent]:
        return [
            NewEvent(
                event_type="test.kernel.recorded",
                aggregate_type="test",
                aggregate_id=uuid.uuid7(),
                payload={"label": self.label, "count": self.count},
            )
        ]


def test_a_concrete_command_must_name_itself():
    with pytest.raises(TypeError, match="command_name"):

        @dataclass(frozen=True, slots=True)
        class Unnamed(Command):
            def build(self, context: CommandContext) -> Sequence[NewEvent]:
                return []


def test_an_abstract_base_need_not_name_itself():
    class PartialCommand(Command):
        """Implements nothing, so it is still abstract and names nothing."""

    assert PartialCommand.__abstractmethods__ == frozenset({"build"})


def test_two_classes_cannot_claim_one_name():
    with pytest.raises(TypeError, match="already owned by"):

        @dataclass(frozen=True, slots=True)
        class Impostor(Command):
            command_name: ClassVar[CommandName] = CommandName.TEST_KERNEL_BASIC

            def build(self, context: CommandContext) -> Sequence[NewEvent]:
                return []


def test_a_slotted_command_is_not_a_duplicate_of_itself():
    #: dataclass(slots=True) rebuilds the class, registering it twice. Reaching
    #: this assertion at all means the second registration was not read as a
    #: collision -- the class would otherwise have raised at import.
    assert BasicCommand(label="x", count=1).label == "x"


def test_the_context_carries_no_stream():
    #: Pinned as a field set rather than left to review: a command holding the
    #: locked stream could append behind idempotency's back.
    assert {field.name for field in fields(CommandContext)} == {"library", "actor"}
