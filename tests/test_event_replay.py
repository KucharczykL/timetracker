"""Folding an existing stream through a registry.

Every family here registers into a registry this module owns, so nothing
declared for a test can reach `DEFAULT_REGISTRY` or another test.
"""

import uuid
from typing import Any, ClassVar, TypedDict

import pytest
from django.db import transaction
from pydantic import ConfigDict, with_config

from games.events.append import AppendResult, lock_stream
from games.events.envelope import RecordedEvent
from games.events.projection import (
    HandlerMap,
    Projector,
    ProjectorFamily,
    ProjectorRegistry,
)
from games.events.replay import (
    PayloadVersionUnsupported,
    ReplayResult,
    StreamNotContiguous,
    replay,
)
from games.events.vocabulary import (
    EventSpec,
    EventTypeRegistry,
    NewEvent,
    UnregisteredEventType,
)
from games.events.wiring import EventWiring
from games.models import LibraryEvent, LibraryEventStreamHead

pytestmark = pytest.mark.django_db

RECORDED = "library.probe.recorded"
UNHANDLED = "library.probe.unhandled"
AWKWARD = "library.probe.awkward"

#: The whole value each family was handed, so a test can compare envelopes
#: rather than a projection of them.
SEEN: list[RecordedEvent] = []
#: Which family saw which sequence, in the order it happened.
ORDER: list[tuple[ProjectorFamily, int]] = []


#: One event type for handled and unhandled.
@with_config(ConfigDict(extra="forbid", strict=True))
class ProbePayload(TypedDict):
    index: int


@with_config(ConfigDict(extra="forbid", strict=True))
class AwkwardPayload(TypedDict):
    """Keys ordered unlike both caller and jsonb."""

    zz: dict[str, int]
    aaa: list[dict[str, int]]
    order: list[int]
    b: int


PROBE_RECORDED = EventSpec(RECORDED, aggregate_type="probe", payload=ProbePayload)
PROBE_UNHANDLED = EventSpec(UNHANDLED, aggregate_type="probe", payload=ProbePayload)
PROBE_AWKWARD = EventSpec(AWKWARD, aggregate_type="probe", payload=AwkwardPayload)

#: Neither sorted nor jsonb's, at every level.
AWKWARD_PAYLOAD: dict[str, Any] = {
    "zz": {"yy": 1, "a": 2},
    "aaa": [{"nn": 1, "c": 2}, {"zzz": 3}],
    "order": [3, 1, 2],
    "b": 4,
}

#: The same trap on the other column.
AWKWARD_METADATA: dict[str, Any] = {"zz": 1, "aaa": 2, "b": 3, "origin": "manual"}

#: This module's own vocabulary, never production's.
EVENT_TYPES = EventTypeRegistry()
for spec in (PROBE_RECORDED, PROBE_UNHANDLED, PROBE_AWKWARD):
    EVENT_TYPES.register(spec)

registry = ProjectorRegistry()
wiring = EventWiring(projectors=registry, event_types=EVENT_TYPES)


class Recorder(Projector, registry=registry):
    family_name = ProjectorFamily.CURRENT_STATE

    def _recorded(self, event: RecordedEvent) -> None:
        SEEN.append(event)
        ORDER.append((ProjectorFamily.CURRENT_STATE, event.sequence))

    handles: ClassVar[HandlerMap] = {
        PROBE_RECORDED: _recorded,
        PROBE_AWKWARD: _recorded,
    }


class SecondRecorder(Projector, registry=registry):
    """A second family on the same event type, so the fold's shape is visible:
    both families see event one before either sees event two."""

    family_name = ProjectorFamily.JOURNAL

    def _recorded(self, event: RecordedEvent) -> None:
        ORDER.append((ProjectorFamily.JOURNAL, event.sequence))

    handles: ClassVar[HandlerMap] = {PROBE_RECORDED: _recorded}


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
        "spec": PROBE_RECORDED,
        "aggregate_id": uuid.uuid7(),
        "payload": {"index": 0},
    }
    fields.update(overrides)
    return NewEvent(**fields)


def append(library, events=None, **overrides: Any) -> AppendResult:
    """One append, folded through this module's wiring."""
    fields: dict[str, Any] = {
        "actor": None,
        "correlation_id": uuid.uuid7(),
        "idempotency_key": f"probe-{uuid.uuid7()}",
        "wiring": wiring,
    }
    fields.update(overrides)
    with transaction.atomic():
        return lock_stream(library).append(events or [make_new_event()], **fields)


def append_stream(library, length: int) -> AppendResult:
    """One append carrying `length` events, so the stream runs 1..length."""
    return append(
        library, [make_new_event(payload={"index": index}) for index in range(length)]
    )


def write_row_directly(library, **overrides: Any) -> LibraryEvent:
    """One event written past append, head advanced."""
    head = LibraryEventStreamHead.objects.get(library=library)
    sequence = head.current_sequence + 1
    fields: dict[str, Any] = {
        "library": library,
        "stream": head,
        "sequence": sequence,
        "event_type": RECORDED,
        "aggregate_id": uuid.uuid7(),
        "correlation_id": uuid.uuid7(),
        "idempotency_key": f"direct-{sequence}",
        "payload": {"index": sequence},
    }
    fields.update(overrides)
    row = LibraryEvent.objects.create(**fields)
    head.current_sequence = sequence
    head.save(update_fields=["current_sequence"])
    return row


def test_an_unregistered_event_type_refuses_the_replay(owned_library):
    append_stream(owned_library, 2)
    write_row_directly(owned_library, event_type="library.probe.forgotten")
    SEEN.clear()

    with pytest.raises(UnregisteredEventType, match="library.probe.forgotten"):
        replay(owned_library, wiring=wiring)

    #: Folded up to the row, nothing after.
    assert [event.sequence for event in SEEN] == [1, 2]


def test_an_unreadable_payload_version_refuses_the_replay(owned_library):
    append_stream(owned_library, 2)
    write_row_directly(owned_library, payload_schema_version=2)
    SEEN.clear()

    with pytest.raises(PayloadVersionUnsupported) as raised:
        replay(owned_library, wiring=wiring)

    message = str(raised.value)
    #: Both versions and the sequence.
    assert "version 2" in message
    assert "version 1" in message
    assert "#3" in message
    assert [event.sequence for event in SEEN] == [1, 2]


def test_an_unreadable_row_is_refused_before_any_family_sees_it(owned_library):
    """No family sees an unvouched payload."""
    LibraryEventStreamHead.objects.create(library=owned_library)
    write_row_directly(owned_library, payload_schema_version=2)

    with pytest.raises(PayloadVersionUnsupported):
        replay(owned_library, wiring=wiring)

    assert SEEN == []
    assert ORDER == []


def test_a_damaged_stream_is_refused_as_damaged_not_as_unreadable(owned_library):
    """Contiguity is checked first."""
    append_stream(owned_library, 2)
    write_row_directly(owned_library, payload_schema_version=2)
    LibraryEvent.objects.filter(sequence=2).delete()

    with pytest.raises(StreamNotContiguous, match="2"):
        replay(owned_library, wiring=wiring)


def test_a_stream_folds_every_event_in_sequence_order(owned_library):
    append_stream(owned_library, 3)
    SEEN.clear()

    result = replay(owned_library, wiring=wiring)

    assert [event.sequence for event in SEEN] == [1, 2, 3]
    assert result == ReplayResult(
        stream_id=owned_library.event_stream_head.id, folded_through=3
    )


def test_an_untouched_stream_folds_nothing(owned_library):
    head = LibraryEventStreamHead.objects.create(library=owned_library)

    result = replay(owned_library, wiring=wiring)

    assert result == ReplayResult(stream_id=head.id, folded_through=0)
    assert SEEN == []


def test_a_library_that_never_appended_replays_to_nothing(owned_library):
    result = replay(owned_library, wiring=wiring)

    assert result == ReplayResult(stream_id=None, folded_through=0)
    assert SEEN == []
    #: A read that provisions rows is a read nobody can run safely.
    assert not LibraryEventStreamHead.objects.filter(library=owned_library).exists()


def test_a_missing_event_refuses_the_replay(owned_library):
    append_stream(owned_library, 4)
    SEEN.clear()
    LibraryEvent.objects.filter(sequence=3).delete()

    with pytest.raises(StreamNotContiguous, match="3"):
        replay(owned_library, wiring=wiring)

    #: Everything before the gap was applied and stays applied: replay owns no
    #: transaction and cannot offer all-or-nothing.
    assert [event.sequence for event in SEEN] == [1, 2]


def test_a_stream_ending_early_refuses_the_replay(owned_library):
    append_stream(owned_library, 3)
    LibraryEvent.objects.filter(sequence=3).delete()

    with pytest.raises(StreamNotContiguous, match="3"):
        replay(owned_library, wiring=wiring)


def test_a_stream_starting_after_one_refuses_the_replay(owned_library):
    append_stream(owned_library, 3)
    LibraryEvent.objects.filter(sequence=1).delete()

    with pytest.raises(StreamNotContiguous, match="1"):
        replay(owned_library, wiring=wiring)


def test_an_event_no_family_handles_is_folded_and_applied_to_nothing(owned_library):
    append(owned_library, [make_new_event(spec=PROBE_UNHANDLED)])

    result = replay(owned_library, wiring=wiring)

    assert result.folded_through == 1
    assert SEEN == []


def test_a_replay_folds_what_the_append_folded(owned_library):
    """The parity property: an event carries the same envelope, in the same
    order, whichever path reached the projector."""
    append_stream(owned_library, 3)
    append(owned_library)
    appended = list(SEEN)
    SEEN.clear()

    replay(owned_library, wiring=wiring)

    assert SEEN == appended


def test_a_payload_reaches_a_projector_in_one_key_order(owned_library):
    """The parity property equality cannot see."""
    append(owned_library, [make_new_event(spec=PROBE_AWKWARD, payload=AWKWARD_PAYLOAD)])
    appended = SEEN[0].payload
    SEEN.clear()

    replay(owned_library, wiring=wiring)
    replayed = SEEN[0].payload

    assert list(appended) == list(replayed) == ["aaa", "b", "order", "zz"]
    assert list(appended["zz"]) == list(replayed["zz"]) == ["a", "yy"]
    assert [list(item) for item in appended["aaa"]] == [["c", "nn"], ["zzz"]]
    assert [list(item) for item in replayed["aaa"]] == [["c", "nn"], ["zzz"]]


def test_source_metadata_reaches_a_projector_in_one_key_order(owned_library):
    """The same property on the other column."""
    append(
        owned_library,
        [make_new_event()],
        source_metadata=AWKWARD_METADATA,
    )
    appended = SEEN[0].source_metadata
    SEEN.clear()

    replay(owned_library, wiring=wiring)
    replayed = SEEN[0].source_metadata

    assert list(appended) == list(replayed) == ["aaa", "b", "origin", "zz"]


def test_each_event_of_one_append_carries_its_own_source_metadata(owned_library):
    """One dict per event, not one shared."""
    append(
        owned_library,
        [make_new_event(), make_new_event()],
        source_metadata=AWKWARD_METADATA,
    )

    first, second = SEEN
    assert first.source_metadata == second.source_metadata
    assert first.source_metadata is not second.source_metadata


def test_a_payloads_lists_keep_the_order_they_were_written_in(owned_library):
    """Keys are sorted; values are not."""
    append(owned_library, [make_new_event(spec=PROBE_AWKWARD, payload=AWKWARD_PAYLOAD)])
    appended = SEEN[0].payload
    SEEN.clear()

    replay(owned_library, wiring=wiring)

    assert appended["order"] == SEEN[0].payload["order"] == [3, 1, 2]
    assert [item["zzz"] for item in appended["aaa"] if "zzz" in item] == [3]


def test_replaying_twice_folds_the_same_events(owned_library):
    append_stream(owned_library, 3)

    SEEN.clear()
    replay(owned_library, wiring=wiring)
    first = list(SEEN)

    SEEN.clear()
    replay(owned_library, wiring=wiring)

    assert SEEN == first


def test_the_fold_is_event_major(owned_library):
    append_stream(owned_library, 2)
    ORDER.clear()

    replay(owned_library, wiring=wiring)

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
        replay(owned_library, wiring=wiring)


def test_events_appended_after_a_replay_belong_to_the_next_one(owned_library):
    append_stream(owned_library, 2)

    first = replay(owned_library, wiring=wiring)
    append_stream(owned_library, 2)
    SEEN.clear()
    second = replay(owned_library, wiring=wiring)

    assert first.folded_through == 2
    assert second.folded_through == 4
    assert [event.sequence for event in SEEN] == [1, 2, 3, 4]


def test_a_replay_folds_one_library_only(owned_library, second_library):
    append_stream(owned_library, 2)
    append_stream(second_library, 3)
    SEEN.clear()

    result = replay(second_library, wiring=wiring)

    assert result.folded_through == 3
    assert {event.library_id for event in SEEN} == {second_library.id}


def test_a_raising_handler_propagates_with_its_notes(owned_library):
    failing_registry = ProjectorRegistry()

    class Failing(Projector, registry=failing_registry):
        family_name = ProjectorFamily.STATS

        def _recorded(self, event: RecordedEvent) -> None:
            raise KeyError("nothing here")

        handles: ClassVar[HandlerMap] = {PROBE_RECORDED: _recorded}

    append(owned_library)

    with pytest.raises(KeyError) as raised:
        replay(
            owned_library,
            wiring=EventWiring(projectors=failing_registry, event_types=EVENT_TYPES),
        )

    assert any(
        "stats" in note and RECORDED in note and "#1" in note
        for note in raised.value.__notes__
    )
