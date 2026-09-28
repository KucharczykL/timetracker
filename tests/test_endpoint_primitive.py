"""The stated-endpoint primitive: its events, columns and check."""

import pytest

from games.checks import endpoint_errors
from games.end_ways import EndWay
from games.endpoint_fields import EndpointColumns, endpoint_constraints
from games.endpoints import ENDPOINTS, PLAYTHROUGH_COMPLETION, PLAYTHROUGH_START
from games.events.vocabulary import DEFAULT_EVENT_TYPES
from games.models import Playthrough


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
