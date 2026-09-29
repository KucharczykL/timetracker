"""The stated-endpoint primitive: its events, columns and check."""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import get_args
from unittest.mock import patch

import pytest

from games.checks import endpoint_errors
from games.commands.endpoint import (
    ActStatement,
    EndpointSentences,
    Rejection,
    WayActStatement,
    correct_endpoint,
    correct_opening_endpoint,
    normalized,
    state_endpoint,
    void_endpoint,
)
from games.end_ways import EndWay
from games.endpoint_fields import (
    EndpointColumns,
    OpeningEndpointColumns,
    WayColumn,
    endpoint_constraints,
)
from games.endpoints import (
    DEVICE_ACCESS_END,
    ENDPOINTS,
    ENTRY_ACCESS_END,
    PLAYTHROUGH_COMPLETION,
    PLAYTHROUGH_START,
    Endpoint,
    OpeningEndpoint,
)
from games.events.device import DeviceWayValue
from games.events.dispatch import CommandRejected
from games.events.endpoint import OpeningEndpointEvents
from games.events.envelope import RecordedEvent
from games.events.vocabulary import DEFAULT_EVENT_TYPES, NewEvent, Unchanged
from games.filters import PlaythroughFilter, way_filter_field
from games.models import DEVICE_WAYS, Device, Playthrough
from games.projectors.device import Devices
from games.reads.endpoints import StatedEndpoint
from games.writes.endpoint import Act, Correct, Nothing, Void, endpoint_move
from timetracker.temporal import TemporalValue


def test_playthrough_endpoints_keep_their_recorded_types() -> None:
    assert PLAYTHROUGH_START.events.family == (
        "library.playthrough.started",
        "library.playthrough.start_corrected",
        "library.playthrough.start_voided",
    )
    assert PLAYTHROUGH_COMPLETION.events.family == (
        "library.playthrough.completed",
        "library.playthrough.completion_corrected",
        "library.playthrough.completion_voided",
    )


@pytest.mark.parametrize("endpoint", ENDPOINTS, ids=lambda endpoint: endpoint.name)
def test_every_endpoint_event_is_registered(endpoint) -> None:
    for spec in endpoint.events.specs:
        assert DEFAULT_EVENT_TYPES.spec_for(spec.event_type) is spec


def test_an_endpoint_without_ways_needs_no_constraint() -> None:
    assert endpoint_constraints(PLAYTHROUGH_START) == ()
    assert endpoint_constraints(PLAYTHROUGH_COMPLETION) == ()


@pytest.mark.parametrize("endpoint", ENDPOINTS, ids=lambda endpoint: endpoint.name)
def test_every_registered_endpoint_matches_its_model(endpoint) -> None:
    assert endpoint_errors(endpoint, endpoint.model) == []


def _start(**changes) -> EndpointColumns:
    columns = {
        "name": "start",
        "model_label": "games.Playthrough",
        "when": "started",
        "lower": "started_lower",
        "upper": "started_upper",
        "marker": "start_recorded_at",
        "note": "start_note",
    }
    return EndpointColumns(**(columns | changes))


def _opening(**changes) -> OpeningEndpointColumns:
    columns = {
        "name": "start",
        "model_label": "games.Playthrough",
        "when": "started",
        "lower": "started_lower",
        "upper": "started_upper",
        "marker": "start_recorded_at",
        "note": "start_note",
    }
    return OpeningEndpointColumns(**(columns | changes))


def test_an_opening_endpoint_refuses_a_way() -> None:
    with pytest.raises(TypeError, match="states no way"):
        _opening(way=WayColumn("name", (EndWay.SOLD,)))


def test_an_opening_endpoint_states_no_unstated_columns() -> None:
    """A sibling of the stated shape, not a subtype."""
    assert _opening().way is None
    assert not hasattr(_opening(), "unstated_columns")
    assert not isinstance(_opening(), EndpointColumns)


def test_the_check_refuses_a_nullable_opening_marker() -> None:
    messages = [error.msg for error in endpoint_errors(_opening(), Playthrough)]
    assert messages == [
        "Endpoint 'start' on games.Playthrough: its marker admits null."
    ]
    assert endpoint_errors(_start(), Playthrough) == []


def _creation() -> RecordedEvent:
    return RecordedEvent(
        id=uuid.uuid7(),
        library_id=uuid.uuid7(),
        stream_id=uuid.uuid7(),
        sequence=1,
        event_type="library.playthrough.created",
        aggregate_id=uuid.uuid7(),
        payload_schema_version=1,
        recorded_at=RECORDED,
        effective_time=MAY,
        actor_id=None,
        correlation_id=uuid.uuid7(),
        causation_id=None,
        source_metadata={},
        idempotency_key="probe",
        payload={},
    )


def test_a_missing_opening_marker_is_reported_once() -> None:
    (error,) = endpoint_errors(_opening(marker="start_stamp"), Playthrough)
    assert "declares no column 'start_stamp'" in error.msg


def test_opening_columns_reads_the_creation() -> None:
    event = _creation()
    columns = Devices().opening_columns(_opening(), event, note="bought")
    assert columns == {
        "started": MAY,
        "start_recorded_at": RECORDED,
        "start_note": "bought",
    }


OPENING_START = OpeningEndpoint.over(
    _opening(), OpeningEndpointEvents(corrected=PLAYTHROUGH_START.events.corrected)
)


def test_an_opening_correction_to_what_is_stated_is_unchanged() -> None:
    answer = correct_opening_endpoint(
        _started_run("x"),
        OPENING_START,
        ActStatement(MAY, "x"),
        same_correction="same day",
        before_event=_refuse,
    )
    assert answer == Unchanged("same day")


def test_an_opening_correction_states_the_corrected_event() -> None:
    (event,) = _events(
        correct_opening_endpoint(
            _started_run(), OPENING_START, ActStatement(None, "x"), same_correction=""
        )
    )
    assert event.spec is PLAYTHROUGH_START.events.corrected
    assert (event.effective_time, event.payload) == (None, {"note": "x"})
    assert OPENING_START.events.family == ("library.playthrough.start_corrected",)


def test_the_check_refuses_a_column_the_model_lacks() -> None:
    (error,) = endpoint_errors(_start(note="start_remark"), Playthrough)
    assert error.id == "games.E014"
    assert "'start_remark'" in error.msg


def test_the_check_refuses_a_bound_over_another_column() -> None:
    (error,) = endpoint_errors(_start(lower="completed_lower"), Playthrough)
    assert "not the TemporalLowerBound of 'started'" in error.msg


def test_the_check_refuses_a_plain_column_as_a_bound() -> None:
    (error,) = endpoint_errors(_start(upper="start_note"), Playthrough)
    assert "not the TemporalUpperBound" in error.msg


def test_the_check_refuses_a_way_endpoint_without_its_constraints() -> None:
    columns = _start(way=WayColumn("name", (EndWay.SOLD,)))
    messages = [error.msg for error in endpoint_errors(columns, Playthrough)]
    assert any("way_known" in message for message in messages)
    assert any("way_with_marker" in message for message in messages)


MAY = TemporalValue.parse("2021-05")
RECORDED = datetime(2026, 9, 28, tzinfo=UTC)
SOLD = WayActStatement(MAY, EndWay.SOLD, "")
SENTENCES = EndpointSentences(
    already_stated=Rejection("stated twice", "Correct it."),
    nothing_to_correct=Rejection("nothing stated", "State it first."),
    same_statement="same statement",
    same_correction="same correction",
    nothing_to_void="nothing to void",
)


def _unstated_run() -> Playthrough:
    return Playthrough(id=uuid.uuid7())


def _started_run(note: str = "") -> Playthrough:
    return Playthrough(
        id=uuid.uuid7(), started=MAY, start_recorded_at=RECORDED, start_note=note
    )


def _events(answer: Sequence[NewEvent] | Unchanged) -> Sequence[NewEvent]:
    assert not isinstance(answer, Unchanged)
    return answer


def _refuse() -> None:
    raise CommandRejected("hook ran", sentence="Hook.")


def test_state_on_an_unstated_endpoint_is_the_act() -> None:
    run = _unstated_run()
    (event,) = _events(
        state_endpoint(
            run, PLAYTHROUGH_START, ActStatement(MAY, "began"), sentences=SENTENCES
        )
    )
    assert event.spec is PLAYTHROUGH_START.events.stated
    assert (event.aggregate_id, event.effective_time) == (run.pk, MAY)
    assert event.payload == {"note": "began"}


def test_the_same_statement_again_is_unchanged_before_the_hook() -> None:
    answer = state_endpoint(
        _started_run(),
        PLAYTHROUGH_START,
        ActStatement(MAY, ""),
        sentences=SENTENCES,
        before_event=_refuse,
    )
    assert answer == Unchanged("same statement")


def test_another_statement_is_refused_before_the_hook() -> None:
    with pytest.raises(CommandRejected) as refused:
        state_endpoint(
            _started_run(),
            PLAYTHROUGH_START,
            ActStatement(None, ""),
            sentences=SENTENCES,
            before_event=_refuse,
        )
    assert refused.value.sentence == "Correct it."


def test_the_hook_runs_before_the_event() -> None:
    with pytest.raises(CommandRejected, match="hook ran"):
        state_endpoint(
            _unstated_run(),
            PLAYTHROUGH_START,
            ActStatement(MAY, ""),
            sentences=SENTENCES,
            before_event=_refuse,
        )


def test_a_correction_of_nothing_is_refused_ahead_of_the_comparison() -> None:
    with pytest.raises(CommandRejected) as refused:
        correct_endpoint(
            _unstated_run(),
            PLAYTHROUGH_START,
            ActStatement(None, ""),
            sentences=SENTENCES,
        )
    assert refused.value.sentence == "State it first."


def test_a_correction_to_what_is_stated_is_unchanged() -> None:
    answer = correct_endpoint(
        _started_run("x"),
        PLAYTHROUGH_START,
        ActStatement(MAY, "x"),
        sentences=SENTENCES,
        before_event=_refuse,
    )
    assert answer == Unchanged("same correction")


def test_a_correction_states_the_corrected_event() -> None:
    (event,) = _events(
        correct_endpoint(
            _started_run(),
            PLAYTHROUGH_START,
            ActStatement(None, ""),
            sentences=SENTENCES,
        )
    )
    assert event.spec is PLAYTHROUGH_START.events.corrected
    assert event.effective_time is None


def test_a_void_of_nothing_is_unchanged_before_the_hook() -> None:
    answer = void_endpoint(
        _unstated_run(), PLAYTHROUGH_START, sentences=SENTENCES, before_event=_refuse
    )
    assert answer == Unchanged("nothing to void")


def test_a_void_runs_the_hook_then_voids() -> None:
    with pytest.raises(CommandRejected, match="hook ran"):
        void_endpoint(
            _started_run(), PLAYTHROUGH_START, sentences=SENTENCES, before_event=_refuse
        )
    (event,) = _events(
        void_endpoint(_started_run(), PLAYTHROUGH_START, sentences=SENTENCES)
    )
    assert (event.spec, event.payload) == (PLAYTHROUGH_START.events.voided, {})


@pytest.mark.parametrize(
    ("held", "wanted", "move"),
    [
        (None, None, Nothing()),
        (None, SOLD, Act(SOLD)),
        ("stated", None, Void()),
        #: Equal values still correct; the command compares.
        ("stated", SOLD, Correct(SOLD)),
    ],
)
def test_the_move_reads_presence_alone(held, wanted, move) -> None:
    stated_endpoint = None if held is None else StatedEndpoint(RECORDED, MAY, "")
    assert endpoint_move(stated_endpoint, wanted) == move


def test_playthrough_filter_keeps_its_endpoint_leaves() -> None:
    fields = PlaythroughFilter.fields
    assert list(fields)[2:6] == ["started", "completed", "is_started", "is_completed"]
    assert fields["started"].metadata_lookup == "started_lower"
    assert fields["completed"].metadata_lookup == "completed_lower"
    assert fields["is_started"].label == "Has a start"
    assert fields["is_completed"].label == "Has a completion"
    assert fields["started"].label is None


def test_a_statement_of_the_wrong_shape_is_a_defect() -> None:
    with pytest.raises(TypeError, match="takes a WayActStatement"):
        state_endpoint(
            Device(id=uuid.uuid7()),
            DEVICE_ACCESS_END,
            ActStatement(MAY, ""),
            sentences=SENTENCES,
        )
    with pytest.raises(TypeError, match="takes a ActStatement"):
        state_endpoint(_unstated_run(), PLAYTHROUGH_START, SOLD, sentences=SENTENCES)


def test_the_check_reports_a_label_naming_no_model() -> None:
    from games.checks import check_endpoints
    from games.endpoints import ENDPOINTS

    broken = Endpoint.over(
        _start(model_label="games.Nowhere"), PLAYTHROUGH_START.events
    )
    with patch("games.checks.ENDPOINTS", (*ENDPOINTS, broken)):
        (error,) = check_endpoints()
    assert "names no model" in error.msg


def test_the_check_refuses_an_endpoint_on_a_conventional_model() -> None:
    from games.models import Platform

    messages = [error.msg for error in endpoint_errors(_start(), Platform)]
    assert any("no projection" in message for message in messages)


def test_the_device_way_literal_spells_every_device_way() -> None:
    assert set(get_args(DeviceWayValue.__value__)) == {way.value for way in DEVICE_WAYS}


def test_a_wayless_endpoint_has_no_way_leaf() -> None:
    with pytest.raises(TypeError, match="states no way"):
        way_filter_field(PLAYTHROUGH_START, label="Way")


def test_the_check_refuses_two_endpoints_sharing_a_name() -> None:
    from games.checks import check_endpoints

    with patch("games.checks.ENDPOINTS", (*ENDPOINTS, PLAYTHROUGH_START)):
        messages = [error.msg for error in check_endpoints()]
    assert any("another endpoint has its name" in message for message in messages)


def test_an_endpoint_without_a_resume_has_three_acts() -> None:
    assert not hasattr(PLAYTHROUGH_START.events, "resumed")
    assert len(PLAYTHROUGH_START.events.family) == 3


def test_a_resumable_endpoint_puts_its_resume_in_the_family() -> None:
    assert ENTRY_ACCESS_END.events.family[-1] == "library.libraryentry.access_resumed"
    assert len(ENTRY_ACCESS_END.events.specs) == 4


def test_normalized_keeps_the_shape_it_was_given() -> None:
    assert normalized(ActStatement(MAY, " began ")) == ActStatement(MAY, "began")
    assert normalized(WayActStatement(MAY, EndWay.SOLD, " gone ")) == (
        WayActStatement(MAY, EndWay.SOLD, "gone")
    )
