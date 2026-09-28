"""The stated-endpoint primitive: its events, columns and check."""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from games.checks import endpoint_errors
from games.commands.endpoint import (
    EndpointSentences,
    Rejection,
    correct_endpoint,
    state_endpoint,
    void_endpoint,
)
from games.end_ways import EndWay
from games.endpoint_fields import EndpointColumns, endpoint_constraints
from games.endpoints import ENDPOINTS, PLAYTHROUGH_COMPLETION, PLAYTHROUGH_START
from games.events.dispatch import CommandRejected
from games.events.vocabulary import DEFAULT_EVENT_TYPES, NewEvent, Unchanged
from games.models import Playthrough
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
    for spec in endpoint.events:
        assert DEFAULT_EVENT_TYPES.spec_for(spec.event_type) is spec


def test_an_endpoint_without_ways_needs_no_constraint() -> None:
    assert endpoint_constraints(PLAYTHROUGH_START) == ()
    assert endpoint_constraints(PLAYTHROUGH_COMPLETION) == ()


def test_a_way_column_comes_with_ways() -> None:
    with pytest.raises(ValueError, match="exactly when"):
        EndpointColumns(
            name="broken",
            model_label="games.Playthrough",
            when="started",
            lower="started_lower",
            upper="started_upper",
            marker="start_recorded_at",
            note="start_note",
            way="start_way",
        )


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
    columns = _start(way="name", ways=(EndWay.SOLD,))
    messages = [error.msg for error in endpoint_errors(columns, Playthrough)]
    assert any("way_known" in message for message in messages)
    assert any("way_with_marker" in message for message in messages)


MAY = TemporalValue.parse("2021-05")
RECORDED = datetime(2026, 9, 28, tzinfo=UTC)
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
            run, PLAYTHROUGH_START, when=MAY, note="began", sentences=SENTENCES
        )
    )
    assert event.spec is PLAYTHROUGH_START.events.stated
    assert (event.aggregate_id, event.effective_time) == (run.pk, MAY)
    assert event.payload == {"note": "began"}


def test_the_same_statement_again_is_unchanged_before_the_hook() -> None:
    answer = state_endpoint(
        _started_run(),
        PLAYTHROUGH_START,
        when=MAY,
        note="",
        sentences=SENTENCES,
        before_event=_refuse,
    )
    assert answer == Unchanged("same statement")


def test_another_statement_is_refused_before_the_hook() -> None:
    with pytest.raises(CommandRejected) as refused:
        state_endpoint(
            _started_run(),
            PLAYTHROUGH_START,
            when=None,
            note="",
            sentences=SENTENCES,
            before_event=_refuse,
        )
    assert refused.value.sentence == "Correct it."


def test_the_hook_runs_before_the_event() -> None:
    with pytest.raises(CommandRejected, match="hook ran"):
        state_endpoint(
            _unstated_run(),
            PLAYTHROUGH_START,
            when=MAY,
            note="",
            sentences=SENTENCES,
            before_event=_refuse,
        )


def test_a_correction_of_nothing_is_refused_ahead_of_the_comparison() -> None:
    with pytest.raises(CommandRejected) as refused:
        correct_endpoint(
            _unstated_run(),
            PLAYTHROUGH_START,
            when=None,
            note="",
            sentences=SENTENCES,
        )
    assert refused.value.sentence == "State it first."


def test_a_correction_to_what_is_stated_is_unchanged() -> None:
    answer = correct_endpoint(
        _started_run("x"),
        PLAYTHROUGH_START,
        when=MAY,
        note="x",
        sentences=SENTENCES,
        before_event=_refuse,
    )
    assert answer == Unchanged("same correction")


def test_a_correction_states_the_corrected_event() -> None:
    (event,) = _events(
        correct_endpoint(
            _started_run(), PLAYTHROUGH_START, when=None, note="", sentences=SENTENCES
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
