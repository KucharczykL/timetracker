"""Folding an existing stream through a registry.

Every family here registers into a registry this module owns, so nothing
declared for a test can reach `DEFAULT_REGISTRY` or another test.
"""

import uuid
from typing import Any, ClassVar

import pytest
from django.db import transaction

from games.events.append import AppendResult, NewEvent, lock_stream
from games.events.envelope import RecordedEvent
from games.events.projection import (
    HandlerMap,
    Projector,
    ProjectorFamily,
    ProjectorRegistry,
)
from games.events.replay import ReplayResult, StreamNotContiguous, replay
from games.models import LibraryEvent, LibraryEventStreamHead

pytestmark = pytest.mark.django_db

RECORDED = "library.probe.recorded"
UNHANDLED = "library.probe.unhandled"

#: The whole value each family was handed, so a test can compare envelopes
#: rather than a projection of them.
SEEN: list[RecordedEvent] = []
#: Which family saw which sequence, in the order it happened.
ORDER: list[tuple[ProjectorFamily, int]] = []

registry = ProjectorRegistry()


class Recorder(Projector, registry=registry):
    family_name = ProjectorFamily.CURRENT_STATE

    def _recorded(self, event: RecordedEvent) -> None:
        SEEN.append(event)
        ORDER.append((ProjectorFamily.CURRENT_STATE, event.sequence))

    handles: ClassVar[HandlerMap] = {RECORDED: _recorded}


class SecondRecorder(Projector, registry=registry):
    """A second family on the same event type, so the fold's shape is visible:
    both families see event one before either sees event two."""

    family_name = ProjectorFamily.JOURNAL

    def _recorded(self, event: RecordedEvent) -> None:
        ORDER.append((ProjectorFamily.JOURNAL, event.sequence))

    handles: ClassVar[HandlerMap] = {RECORDED: _recorded}


@pytest.fixture(autouse=True)
def forget_previous_calls():
    for sink in (SEEN, ORDER):
        sink.clear()
    yield
    for sink in (SEEN, ORDER):
        sink.clear()


@pytest.fixture
def second_library(django_user_model):
    return django_user_model.objects.create_user(
        username="second-owner", password="p"
    ).library


def make_new_event(**overrides: Any) -> NewEvent:
    fields: dict[str, Any] = {
        "event_type": RECORDED,
        "aggregate_type": "probe",
        "aggregate_id": uuid.uuid7(),
        "payload": {"probe": True},
    }
    fields.update(overrides)
    return NewEvent(**fields)


def append(library, events=None, **overrides: Any) -> AppendResult:
    """One append of `events`, folded through this module's registry."""
    fields: dict[str, Any] = {
        "actor": None,
        "correlation_id": uuid.uuid7(),
        "idempotency_key": f"probe-{uuid.uuid7()}",
        "registry": registry,
    }
    fields.update(overrides)
    with transaction.atomic():
        return lock_stream(library).append(events or [make_new_event()], **fields)


def append_stream(library, length: int) -> AppendResult:
    """One append carrying `length` events, so the stream runs 1..length."""
    return append(
        library, [make_new_event(payload={"index": index}) for index in range(length)]
    )


def test_a_stream_folds_every_event_in_sequence_order(owned_library):
    append_stream(owned_library, 3)
    SEEN.clear()

    result = replay(owned_library, registry=registry)

    assert [event.sequence for event in SEEN] == [1, 2, 3]
    assert result == ReplayResult(
        stream_id=owned_library.event_stream_head.id, folded_through=3
    )


def test_an_untouched_stream_folds_nothing(owned_library):
    head = LibraryEventStreamHead.objects.create(library=owned_library)

    result = replay(owned_library, registry=registry)

    assert result == ReplayResult(stream_id=head.id, folded_through=0)
    assert SEEN == []


def test_a_library_that_never_appended_replays_to_nothing(owned_library):
    result = replay(owned_library, registry=registry)

    assert result == ReplayResult(stream_id=None, folded_through=0)
    assert SEEN == []
    #: A read that provisions rows is a read nobody can run safely.
    assert not LibraryEventStreamHead.objects.filter(library=owned_library).exists()


def test_a_missing_event_refuses_the_replay(owned_library):
    append_stream(owned_library, 4)
    SEEN.clear()
    LibraryEvent.objects.filter(sequence=3).delete()

    with pytest.raises(StreamNotContiguous, match="3"):
        replay(owned_library, registry=registry)

    #: Everything before the gap was applied and stays applied: replay owns no
    #: transaction and cannot offer all-or-nothing.
    assert [event.sequence for event in SEEN] == [1, 2]


def test_a_stream_ending_early_refuses_the_replay(owned_library):
    append_stream(owned_library, 3)
    LibraryEvent.objects.filter(sequence=3).delete()

    with pytest.raises(StreamNotContiguous, match="3"):
        replay(owned_library, registry=registry)


def test_a_stream_starting_after_one_refuses_the_replay(owned_library):
    append_stream(owned_library, 3)
    LibraryEvent.objects.filter(sequence=1).delete()

    with pytest.raises(StreamNotContiguous, match="1"):
        replay(owned_library, registry=registry)


def test_an_event_no_family_handles_is_folded_and_applied_to_nothing(owned_library):
    append(owned_library, [make_new_event(event_type=UNHANDLED)])

    result = replay(owned_library, registry=registry)

    assert result.folded_through == 1
    assert SEEN == []


def test_a_replay_folds_what_the_append_folded(owned_library):
    """The parity property: an event carries the same envelope, in the same
    order, whichever path reached the projector."""
    append_stream(owned_library, 3)
    append(owned_library)
    appended = list(SEEN)
    SEEN.clear()

    replay(owned_library, registry=registry)

    assert SEEN == appended


def test_replaying_twice_folds_the_same_events(owned_library):
    append_stream(owned_library, 3)

    SEEN.clear()
    replay(owned_library, registry=registry)
    first = list(SEEN)

    SEEN.clear()
    replay(owned_library, registry=registry)

    assert SEEN == first


def test_the_fold_is_event_major(owned_library):
    append_stream(owned_library, 2)
    ORDER.clear()

    replay(owned_library, registry=registry)

    assert ORDER == [
        (ProjectorFamily.CURRENT_STATE, 1),
        (ProjectorFamily.JOURNAL, 1),
        (ProjectorFamily.CURRENT_STATE, 2),
        (ProjectorFamily.JOURNAL, 2),
    ]


@pytest.mark.parametrize("length", [10, 70])
def test_a_replay_costs_two_queries_whatever_the_stream_holds(
    owned_library, django_assert_num_queries, length
):
    append_stream(owned_library, length)

    #: The head, and the cursor the rows stream from. The fetches against that
    #: cursor are not queries, and neither is anything per event.
    with django_assert_num_queries(2):
        replay(owned_library, registry=registry)


def test_events_appended_after_a_replay_belong_to_the_next_one(owned_library):
    append_stream(owned_library, 2)

    first = replay(owned_library, registry=registry)
    append_stream(owned_library, 2)
    SEEN.clear()
    second = replay(owned_library, registry=registry)

    assert first.folded_through == 2
    assert second.folded_through == 4
    assert [event.sequence for event in SEEN] == [1, 2, 3, 4]


def test_a_replay_folds_one_library_only(owned_library, second_library):
    append_stream(owned_library, 2)
    append_stream(second_library, 3)
    SEEN.clear()

    result = replay(second_library, registry=registry)

    assert result.folded_through == 3
    assert {event.library_id for event in SEEN} == {second_library.id}


def test_a_raising_handler_propagates_with_its_notes(owned_library):
    failing_registry = ProjectorRegistry()

    class Failing(Projector, registry=failing_registry):
        family_name = ProjectorFamily.STATS

        def _recorded(self, event: RecordedEvent) -> None:
            raise KeyError("nothing here")

        handles: ClassVar[HandlerMap] = {RECORDED: _recorded}

    append(owned_library)

    with pytest.raises(KeyError) as raised:
        replay(owned_library, registry=failing_registry)

    assert any(
        "stats" in note and RECORDED in note and "#1" in note
        for note in raised.value.__notes__
    )
