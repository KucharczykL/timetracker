"""What a library states about untracked playtime."""

import uuid
from datetime import timedelta
from typing import get_args

import pytest

from games.events.historical_playtime import (
    HISTORICALPLAYTIME_CREATED,
    HISTORICALPLAYTIME_REMOVED,
    HISTORICALPLAYTIME_RESTATED,
    HISTORICALPLAYTIME_RESTORED,
    HistoricalPlaytimeRunPayload,
    ProvenanceValue,
    historicalplaytime_created,
    historicalplaytime_removed,
    historicalplaytime_restated,
    historicalplaytime_restored,
    sorted_runs,
)
from games.events.references import ReferenceArity
from games.events.vocabulary import DEFAULT_EVENT_TYPES, PayloadInvalid
from games.models import HistoricalPlaytimeProvenance
from timetracker.temporal import TemporalValue

PLAYER_GAME = uuid.uuid7()
RUN_A = uuid.uuid7()
RUN_B = uuid.uuid7()
DEVICE = {
    "kind": "device",
    "id": str(uuid.uuid7()),
    "label": "Steam Deck",
    "detail": "",
}


SHARED_ID = str(uuid.uuid7())


def a_member(run: uuid.UUID) -> HistoricalPlaytimeRunPayload:
    return {"id": str(uuid.uuid7()), "playthrough": str(run)}


def a_statement(**stated) -> dict:
    return {
        "player_game": str(PLAYER_GAME),
        "playthroughs": sorted_runs([a_member(RUN_A)]),
        "duration_seconds": 360000,
        "provenance": "estimated",
        "device": None,
        "emulated": False,
        "note": "",
        "release": None,
        "source": None,
    } | stated


def validated(payload: dict) -> dict:
    return DEFAULT_EVENT_TYPES.validate(HISTORICALPLAYTIME_CREATED.event_type, payload)


def a_creation(**stated):
    return historicalplaytime_created(
        **{
            "player_game_id": PLAYER_GAME,
            "runs": [a_member(RUN_A)],
            "duration": timedelta(hours=1),
            "when": TemporalValue.unknown(),
            "provenance": "estimated",
            "device": None,
            "emulated": False,
            "note": "",
        }
        | stated
    )


def test_the_event_types_are_spelled_once_and_forever():
    assert HISTORICALPLAYTIME_CREATED.event_type == "library.historicalplaytime.created"
    assert (
        HISTORICALPLAYTIME_RESTATED.event_type == "library.historicalplaytime.restated"
    )
    assert HISTORICALPLAYTIME_REMOVED.event_type == "library.historicalplaytime.removed"
    assert (
        HISTORICALPLAYTIME_RESTORED.event_type == "library.historicalplaytime.restored"
    )
    for spec in (
        HISTORICALPLAYTIME_CREATED,
        HISTORICALPLAYTIME_RESTATED,
        HISTORICALPLAYTIME_REMOVED,
        HISTORICALPLAYTIME_RESTORED,
    ):
        assert spec.aggregate_type == "historicalplaytime"


def test_a_statement_round_trips():
    payload = a_statement(device=DEVICE)
    assert validated(payload) == payload


@pytest.mark.parametrize(
    "broken",
    [
        {"playthroughs": []},
        {"playthroughs": [a_member(RUN_A), a_member(RUN_A)]},
        {
            "playthroughs": sorted_runs(
                [
                    a_member(RUN_A) | {"id": SHARED_ID},
                    a_member(RUN_B) | {"id": SHARED_ID},
                ]
            )
        },
        {"playthroughs": sorted_runs([a_member(RUN_A), a_member(RUN_B)])[::-1]},
        {"duration_seconds": 0},
        {"duration_seconds": -1},
        {"duration_seconds": "360000"},
        {"provenance": "guessed"},
        {"release": DEVICE},
        {"source": {"provider": "steam"}},
        {"extra": True},
    ],
    ids=[
        "no-runs",
        "repeated-run",
        "repeated-id",
        "unsorted-runs",
        "zero-duration",
        "negative-duration",
        "lax-integer",
        "unknown-provenance",
        "release-stated",
        "source-stated",
        "extra-key",
    ],
)
def test_a_broken_statement_is_refused(broken):
    with pytest.raises(PayloadInvalid):
        validated(a_statement(**broken))


def test_a_missing_key_is_refused():
    payload = a_statement()
    del payload["note"]
    with pytest.raises(PayloadInvalid):
        validated(payload)


def test_the_provenance_literal_matches_the_choices():
    """A payload is read back as text."""
    #: __value__ reads through the PEP 695 alias.
    assert set(get_args(ProvenanceValue.__value__)) == set(
        HistoricalPlaytimeProvenance.values
    )


def test_the_restatement_carries_the_statement_alone():
    """Creation adds one optional key; restatement none."""
    assert HISTORICALPLAYTIME_RESTATED.payload in (
        HISTORICALPLAYTIME_CREATED.payload.__orig_bases__
    )
    assert set(HISTORICALPLAYTIME_CREATED.payload.__annotations__) - set(
        HISTORICALPLAYTIME_RESTATED.payload.__annotations__
    ) == {"reclassified_from"}


def test_the_creation_may_name_the_session_it_came_from():
    session = uuid.uuid7()
    event = a_creation(reclassified_from=session)
    assert event.payload["reclassified_from"] == str(session)
    assert validated(event.payload) == event.payload
    assert "reclassified_from" not in a_creation().payload


def test_the_session_key_is_absent_not_null():
    with pytest.raises(PayloadInvalid):
        validated(a_statement() | {"reclassified_from": None})


def test_a_restatement_refuses_the_session_key():
    with pytest.raises(PayloadInvalid):
        DEFAULT_EVENT_TYPES.validate(
            HISTORICALPLAYTIME_RESTATED.event_type,
            a_statement() | {"reclassified_from": str(uuid.uuid7())},
        )


def test_the_references_are_enumerated():
    fields = DEFAULT_EVENT_TYPES.reference_fields_for(
        HISTORICALPLAYTIME_CREATED.event_type
    )
    assert fields == {"device": ReferenceArity.OPTIONAL}


def test_the_runs_sort_by_run_text():
    members = [a_member(RUN_B), a_member(RUN_A)]
    assert [member["playthrough"] for member in sorted_runs(members)] == sorted(
        [str(RUN_B), str(RUN_A)]
    )


def test_the_when_rides_on_the_envelope():
    event = a_creation(when=TemporalValue.parse("2005~"))
    assert event.effective_time is not None
    assert event.effective_time.canonical == "2005~"
    assert "when" not in event.payload


def test_an_unknown_when_is_a_null_effective_time():
    assert a_creation(when=TemporalValue.unknown()).effective_time is None


def test_the_identity_may_be_stated():
    stated = uuid.uuid7()
    assert a_creation(record_id=stated).aggregate_id == stated


def test_a_duration_is_whole_seconds():
    event = a_creation(duration=timedelta(hours=1, seconds=30))
    assert event.payload["duration_seconds"] == 3630


def test_a_restatement_carries_the_same_shape():
    record = uuid.uuid7()
    event = historicalplaytime_restated(
        record,
        player_game_id=PLAYER_GAME,
        runs=[a_member(RUN_B), a_member(RUN_A)],
        duration=timedelta(hours=2),
        when=TemporalValue.parse("2006"),
        provenance="manually_entered",
        device=DEVICE,
        emulated=True,
        note="halved",
    )
    assert event.aggregate_id == record
    assert event.spec is HISTORICALPLAYTIME_RESTATED
    assert event.payload == validated(event.payload)
    assert [m["playthrough"] for m in event.payload["playthroughs"]] == sorted(
        [str(RUN_A), str(RUN_B)]
    )


def test_the_mark_events_carry_nothing():
    record = uuid.uuid7()
    assert historicalplaytime_removed(record).payload == {}
    assert historicalplaytime_restored(record).payload == {}
    assert historicalplaytime_removed(record).aggregate_id == record
