import uuid
from collections.abc import Sequence
from dataclasses import dataclass, fields
from typing import ClassVar

import pytest

from games.events.append import NewEvent
from games.events.dispatch import (
    Command,
    CommandContext,
    CommandName,
    canonical_command_input,
)
from games.events.idempotency import fingerprint_command_input
from timetracker.temporal import TemporalValue


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


@dataclass(frozen=True, slots=True)
class TemporalCommand(Command):
    command_name: ClassVar[CommandName] = CommandName.TEST_KERNEL_TEMPORAL
    when: TemporalValue

    def build(self, context: CommandContext) -> Sequence[NewEvent]:
        return [
            NewEvent(
                event_type="test.kernel.recorded",
                aggregate_type="test",
                aggregate_id=uuid.uuid7(),
                payload={},
                effective_time=self.when,
            )
        ]


class UnshapedCommand(Command):
    """A command that is not a dataclass, and so has no fields to fingerprint."""

    command_name: ClassVar[CommandName] = CommandName.TEST_KERNEL_UNSHAPED

    def build(self, context: CommandContext) -> Sequence[NewEvent]:
        return []


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


def test_canonical_input_nests_name_and_fields():
    #: Nested rather than merged: a flat dict would let a command field named
    #: "command" replace the command's own identity.
    assert canonical_command_input(BasicCommand(label="x", count=1)) == {
        "command": "test.kernel.basic",
        "fields": {"label": "x", "count": 1},
    }


def test_canonical_input_reads_temporal_values_shallowly():
    when = TemporalValue.from_year(2026)
    canonical = canonical_command_input(TemporalCommand(when=when))

    #: asdict() would have destructured this into TemporalValue's private
    #: layout, so idempotency's canonicalizer would never see the value it
    #: exists to reduce to a canonical string.
    assert canonical["fields"]["when"] is when


def test_canonical_input_distinguishes_temporal_values():
    same = fingerprint_command_input(
        canonical_command_input(TemporalCommand(when=TemporalValue.from_year(2026)))
    )
    other = fingerprint_command_input(
        canonical_command_input(TemporalCommand(when=TemporalValue.from_year(2025)))
    )

    assert same != other


def test_a_command_that_is_not_a_dataclass_is_rejected():
    with pytest.raises(TypeError, match="not a dataclass"):
        canonical_command_input(UnshapedCommand())


def test_the_command_name_enters_the_fingerprint():
    #: Identical fields under two names. Without the name, one key issued for
    #: either would replay the other's sequence range.
    basic = fingerprint_command_input(
        canonical_command_input(BasicCommand(label="x", count=1))
    )
    twin = fingerprint_command_input(
        canonical_command_input(TwinCommand(label="x", count=1))
    )

    assert basic != twin


def test_the_context_carries_no_stream():
    #: Pinned as a field set rather than left to review: a command holding the
    #: locked stream could append behind idempotency's back.
    assert {field.name for field in fields(CommandContext)} == {"library", "actor"}
