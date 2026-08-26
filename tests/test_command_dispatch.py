import uuid
from collections.abc import Sequence
from dataclasses import dataclass, fields
from typing import ClassVar, TypedDict

import pytest
from django.db import OperationalError, transaction
from pydantic import ConfigDict, with_config
from test_event_retry import wrapped

from games.events import dispatch as dispatch_module
from games.events.dispatch import (
    Command,
    CommandContext,
    CommandName,
    CommandNotPermitted,
    CommandRejected,
    CommandVocabulary,
    authorize,
    canonical_command_input,
    dispatch,
    resolve_correlation_id,
    validate_idempotency_key,
)
from games.events.idempotency import IdempotencyKeyMismatch, fingerprint_command_input
from games.events.retry import NestedTransactionNotSupported
from games.events.vocabulary import EventSpec, EventTypeRegistry, NewEvent
from games.events.wiring import EventWiring
from games.models import LibraryEvent
from timetracker.temporal import TemporalValue

STRICT_CONFIG = ConfigDict(extra="forbid", strict=True)


@with_config(STRICT_CONFIG)
class CommandPayload(TypedDict):
    label: str
    count: int
    library: str
    actor: int


@with_config(STRICT_CONFIG)
class TwinPayload(TypedDict):
    label: str
    count: int


@with_config(STRICT_CONFIG)
class TemporalPayload(TypedDict):
    """No keys: the time is the fact."""


@with_config(STRICT_CONFIG)
class AttemptPayload(TypedDict):
    attempt: int


#: One spec per payload shape.
COMMAND_RECORDED = EventSpec(
    "test.command.recorded", aggregate_type="test", payload=CommandPayload
)
TWIN_RECORDED = EventSpec(
    "test.command.twin.recorded", aggregate_type="test", payload=TwinPayload
)
TEMPORAL_RECORDED = EventSpec(
    "test.command.temporal.recorded", aggregate_type="test", payload=TemporalPayload
)
FLAKY_RECORDED = EventSpec(
    "test.command.flaky.recorded", aggregate_type="test", payload=AttemptPayload
)

#: This module's vocabulary. Projector tests import these.
EVENT_TYPES = EventTypeRegistry()
for spec in (COMMAND_RECORDED, TWIN_RECORDED, TEMPORAL_RECORDED, FLAKY_RECORDED):
    EVENT_TYPES.register(spec)
WIRING = EventWiring(event_types=EVENT_TYPES)


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


class DispatchProbeName(CommandVocabulary):
    """Names for the doubles that exercise dispatch."""

    BASIC = "test.command.basic"
    TWIN = "test.command.twin"
    TEMPORAL = "test.command.temporal"
    UNSHAPED = "test.command.unshaped"
    REJECTING = "test.command.rejecting"
    FLAKY = "test.command.flaky"


@dataclass(frozen=True, slots=True)
class BasicCommand(Command):
    command_name: ClassVar[CommandVocabulary] = DispatchProbeName.BASIC
    label: str
    count: int

    def build(self, context: CommandContext) -> Sequence[NewEvent]:
        return [
            COMMAND_RECORDED.new(
                aggregate_id=uuid.uuid7(),
                #: Records what the context handed it, so a test can assert the
                #: command saw the library and actor dispatch authorized.
                payload={
                    "label": self.label,
                    "count": self.count,
                    "library": str(context.library.pk),
                    "actor": context.actor.pk,
                },
            )
        ]


@dataclass(frozen=True, slots=True)
class TwinCommand(Command):
    """BasicCommand's fields exactly, under another name, so a shared key can
    be shown to be refused on the name alone."""

    command_name: ClassVar[CommandVocabulary] = DispatchProbeName.TWIN
    label: str
    count: int

    def build(self, context: CommandContext) -> Sequence[NewEvent]:
        return [
            TWIN_RECORDED.new(
                aggregate_id=uuid.uuid7(),
                payload={"label": self.label, "count": self.count},
            )
        ]


@dataclass(frozen=True, slots=True)
class TemporalCommand(Command):
    command_name: ClassVar[CommandVocabulary] = DispatchProbeName.TEMPORAL
    when: TemporalValue

    def build(self, context: CommandContext) -> Sequence[NewEvent]:
        return [
            TEMPORAL_RECORDED.new(
                aggregate_id=uuid.uuid7(),
                payload={},
                effective_time=self.when,
            )
        ]


class UnshapedCommand(Command):
    """A command that is not a dataclass, and so has no fields to fingerprint."""

    command_name: ClassVar[CommandVocabulary] = DispatchProbeName.UNSHAPED

    def build(self, context: CommandContext) -> Sequence[NewEvent]:
        return []


@dataclass(frozen=True, slots=True)
class RejectingCommand(Command):
    command_name: ClassVar[CommandVocabulary] = DispatchProbeName.REJECTING

    def build(self, context: CommandContext) -> Sequence[NewEvent]:
        raise CommandRejected("Current state does not permit this.")


@dataclass(frozen=True, slots=True)
class FlakyCommand(Command):
    """Fails its first attempt the way PostgreSQL kills a deadlocked one.

    The attempt counter is a class attribute because the command is frozen and
    a rolled-back attempt leaves no row to count. That is an effect outside the
    database inside a retried operation, which `run_in_transaction` documents as
    forbidden -- knowingly, because it is the only way to make a command fail
    once and then succeed.
    """

    command_name: ClassVar[CommandVocabulary] = DispatchProbeName.FLAKY
    attempts: ClassVar[int] = 0

    def build(self, context: CommandContext) -> Sequence[NewEvent]:
        type(self).attempts += 1
        if type(self).attempts == 1:
            raise wrapped(OperationalError, "40P01")
        return [
            FLAKY_RECORDED.new(
                aggregate_id=uuid.uuid7(),
                payload={"attempt": type(self).attempts},
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
            command_name: ClassVar[CommandVocabulary] = DispatchProbeName.BASIC

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
        "command": "test.command.basic",
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


@pytest.mark.django_db(transaction=True)
def test_a_dispatched_command_appends_its_events(owned_user, owned_library):
    result = dispatch(
        BasicCommand(label="x", count=1),
        actor=owned_user,
        library=owned_library,
        idempotency_key="first",
        source_metadata={"origin": "manual"},
        wiring=WIRING,
    )

    assert result.replayed is False
    assert (result.first_sequence, result.last_sequence) == (1, 1)

    event = LibraryEvent.objects.get(library=owned_library)
    assert event.sequence == 1
    assert event.actor_id == owned_user.pk
    assert event.correlation_id == result.correlation_id
    assert event.idempotency_key == "first"
    assert event.source_metadata == {"origin": "manual"}


@pytest.mark.django_db(transaction=True)
def test_repeating_a_key_replays_the_original_range(owned_user, owned_library):
    command = BasicCommand(label="x", count=1)
    first = dispatch(
        command,
        actor=owned_user,
        library=owned_library,
        idempotency_key="same",
        wiring=WIRING,
    )
    second = dispatch(
        command,
        actor=owned_user,
        library=owned_library,
        idempotency_key="same",
        wiring=WIRING,
    )

    assert second.replayed is True
    assert (second.first_sequence, second.last_sequence) == (
        first.first_sequence,
        first.last_sequence,
    )
    assert LibraryEvent.objects.filter(library=owned_library).count() == 1


@pytest.mark.django_db(transaction=True)
def test_repeating_a_key_over_changed_fields_is_refused(owned_user, owned_library):
    dispatch(
        BasicCommand(label="x", count=1),
        actor=owned_user,
        library=owned_library,
        idempotency_key="same",
        wiring=WIRING,
    )

    with pytest.raises(IdempotencyKeyMismatch):
        dispatch(
            BasicCommand(label="x", count=2),
            actor=owned_user,
            library=owned_library,
            idempotency_key="same",
            wiring=WIRING,
        )


@pytest.mark.django_db(transaction=True)
def test_repeating_a_key_under_another_command_name_is_refused(
    owned_user, owned_library
):
    #: Identical fields. Only the command's name distinguishes these, which is
    #: why it is part of the canonical input.
    dispatch(
        BasicCommand(label="x", count=1),
        actor=owned_user,
        library=owned_library,
        idempotency_key="same",
        wiring=WIRING,
    )

    with pytest.raises(IdempotencyKeyMismatch):
        dispatch(
            TwinCommand(label="x", count=1),
            actor=owned_user,
            library=owned_library,
            idempotency_key="same",
            wiring=WIRING,
        )


@pytest.mark.django_db(transaction=True)
def test_build_receives_the_dispatchers_library_and_actor(owned_user, owned_library):
    dispatch(
        BasicCommand(label="x", count=1),
        actor=owned_user,
        library=owned_library,
        idempotency_key="first",
        wiring=WIRING,
    )

    event = LibraryEvent.objects.get(library=owned_library)
    assert event.payload["library"] == str(owned_library.pk)
    assert event.payload["actor"] == owned_user.pk


@pytest.mark.django_db(transaction=True)
def test_a_rejected_command_appends_nothing(owned_user, owned_library):
    with pytest.raises(CommandRejected):
        dispatch(
            RejectingCommand(),
            actor=owned_user,
            library=owned_library,
            idempotency_key="first",
            wiring=WIRING,
        )

    assert not LibraryEvent.objects.filter(library=owned_library).exists()


@pytest.mark.django_db(transaction=True)
def test_authorization_precedes_any_query(
    owned_user, other_library, django_assert_num_queries
):
    #: The assertion that matters is the query count, not a row count
    #: afterwards: a rejected dispatch rolls back either way, so only this can
    #: tell that no lock was ever taken on another library's stream head.
    with django_assert_num_queries(0), pytest.raises(CommandNotPermitted):
        dispatch(
            BasicCommand(label="x", count=1),
            actor=owned_user,
            library=other_library,
            idempotency_key="first",
            wiring=WIRING,
        )


@pytest.mark.django_db(transaction=True)
def test_dispatch_refuses_to_nest(owned_user, owned_library):
    with transaction.atomic(), pytest.raises(NestedTransactionNotSupported):
        dispatch(
            BasicCommand(label="x", count=1),
            actor=owned_user,
            library=owned_library,
            idempotency_key="first",
            wiring=WIRING,
        )


@pytest.mark.django_db(transaction=True)
def test_a_retryable_failure_is_retried_into_one_append(owned_user, owned_library):
    FlakyCommand.attempts = 0

    result = dispatch(
        FlakyCommand(),
        actor=owned_user,
        library=owned_library,
        idempotency_key="first",
        wiring=WIRING,
    )

    assert FlakyCommand.attempts == 2
    assert result.replayed is False
    events = LibraryEvent.objects.filter(library=owned_library)
    assert [event.payload["attempt"] for event in events] == [2]


@pytest.mark.django_db(transaction=True)
def test_the_correlation_id_is_generated_once_per_dispatch(
    owned_user,
    owned_library,
    monkeypatch,
):
    #: Counted rather than read off the events: a rolled-back attempt leaves no
    #: rows, so the surviving ones look identical whether the ID was generated
    #: once per dispatch or once per attempt.
    calls = 0
    resolve = dispatch_module.resolve_correlation_id

    def counting_resolve(correlation_id):
        nonlocal calls
        calls += 1
        return resolve(correlation_id)

    monkeypatch.setattr(dispatch_module, "resolve_correlation_id", counting_resolve)
    FlakyCommand.attempts = 0

    dispatch(
        FlakyCommand(),
        actor=owned_user,
        library=owned_library,
        idempotency_key="first",
        wiring=WIRING,
    )

    assert FlakyCommand.attempts == 2
    assert calls == 1


@pytest.mark.django_db(transaction=True)
def test_a_supplied_correlation_id_is_shared_across_dispatches(
    owned_user, owned_library
):
    shared = uuid.uuid7()

    for key in ("first", "second"):
        result = dispatch(
            BasicCommand(label=key, count=1),
            actor=owned_user,
            library=owned_library,
            idempotency_key=key,
            correlation_id=shared,
            wiring=WIRING,
        )
        assert result.correlation_id == shared

    correlation_ids = {
        event.correlation_id
        for event in LibraryEvent.objects.filter(library=owned_library)
    }
    assert correlation_ids == {shared}


def test_the_allowlist_holds_real_commands_only():
    #: Every entry is a thing the system does.
    assert not [name for name in CommandName if name.value.startswith("test.")], (
        f"CommandName holds {[name.value for name in CommandName]}. Names only "
        "a test uses belong in that test's own CommandVocabulary."
    )


def test_two_vocabularies_cannot_claim_one_name():
    #: The registry keys on the name, not the member.
    class Borrowed(CommandVocabulary):
        TRACK = CommandName.PLAYERGAME_TRACK.value

    with pytest.raises(TypeError, match="already owned by"):

        @dataclass(frozen=True, slots=True)
        class Impostor(Command):
            command_name: ClassVar[CommandVocabulary] = Borrowed.TRACK

            def build(self, context: CommandContext) -> Sequence[NewEvent]:
                return []


def test_the_context_carries_no_stream():
    #: Pinned as a field set rather than left to review: a command holding the
    #: locked stream could append behind idempotency's back.
    assert {field.name for field in fields(CommandContext)} == {"library", "actor"}
