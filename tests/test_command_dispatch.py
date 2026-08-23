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
    CommandNotPermitted,
    authorize,
    canonical_command_input,
    resolve_correlation_id,
    validate_idempotency_key,
)
from games.events.idempotency import fingerprint_command_input
from timetracker.temporal import TemporalValue


@pytest.fixture
def other_user(django_user_model, db):
    return django_user_model.objects.create_user(username="other-owner", password="p")


@pytest.fixture
def other_library(other_user):
    return other_user.library


@pytest.fixture
def staff_user(django_user_model, db):
    return django_user_model.objects.create_user(
        username="staff-owner", password="p", is_staff=True, is_superuser=True
    )


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


def test_the_owner_is_permitted(owned_user, owned_library):
    assert authorize(owned_user, owned_library) is None


def test_another_users_library_is_refused(owned_user, other_library):
    with pytest.raises(CommandNotPermitted):
        authorize(owned_user, other_library)


def test_an_inactive_user_is_refused(owned_user, owned_library):
    owned_user.is_active = False

    with pytest.raises(CommandNotPermitted):
        authorize(owned_user, owned_library)


def test_staff_is_not_a_bypass(staff_user, other_library):
    #: Staff status grants nothing at the write boundary. An assisted repair is
    #: an explicit act, not a privilege that ordinary dispatch honours.
    with pytest.raises(CommandNotPermitted):
        authorize(staff_user, other_library)


def test_a_refusal_names_neither_the_other_user_nor_their_library(
    owned_user, other_user, other_library
):
    with pytest.raises(CommandNotPermitted) as refusal:
        authorize(owned_user, other_library)

    message = str(refusal.value)
    assert other_user.username not in message
    assert str(other_library.pk) not in message


def test_an_absent_correlation_id_is_generated():
    assert resolve_correlation_id(None).version == 7


def test_a_supplied_uuid7_is_used_verbatim():
    supplied = uuid.uuid7()

    assert resolve_correlation_id(supplied) == supplied


def test_a_uuid4_correlation_id_is_refused():
    #: The column is a UUIDv7Field over a domain with a version check, so a
    #: uuid4 would otherwise die as a raw IntegrityError from inside the append.
    with pytest.raises(ValueError):
        resolve_correlation_id(uuid.uuid4())


def test_an_empty_idempotency_key_is_refused():
    with pytest.raises(ValueError):
        validate_idempotency_key("")


def test_an_overlong_idempotency_key_is_refused():
    with pytest.raises(ValueError):
        validate_idempotency_key("k" * 256)


def test_a_key_at_the_column_limit_is_accepted():
    assert validate_idempotency_key("k" * 255) is None


def test_the_context_carries_no_stream():
    #: Pinned as a field set rather than left to review: a command holding the
    #: locked stream could append behind idempotency's back.
    assert {field.name for field in fields(CommandContext)} == {"library", "actor"}
