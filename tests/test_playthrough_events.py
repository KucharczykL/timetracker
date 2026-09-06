"""What a library records about a run."""

import uuid
from typing import get_args

import pytest

from games.events.playthrough import (
    PLAYTHROUGH_COMPLETED,
    PLAYTHROUGH_CREATED,
    PLAYTHROUGH_NAME_CHANGED,
    PLAYTHROUGH_NOTE_CHANGED,
    PLAYTHROUGH_STARTED,
    PlaythroughKindValue,
    playthrough_completed,
    playthrough_created,
    playthrough_name_changed,
    playthrough_note_changed,
    playthrough_started,
)
from games.events.vocabulary import DEFAULT_EVENT_TYPES, PayloadInvalid
from games.models import PlaythroughKind
from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.untracked_games


def test_the_creation_event_is_in_the_default_vocabulary():
    registered = DEFAULT_EVENT_TYPES.spec_for("library.playthrough.created")

    assert registered is PLAYTHROUGH_CREATED
    assert registered.aggregate_type == "playthrough"


def test_the_kind_literal_matches_the_choices():
    """A payload is read back as text."""
    #: __value__ reads through the PEP 695 alias.
    assert set(get_args(PlaythroughKindValue.__value__)) == set(PlaythroughKind.values)


def test_the_payload_refuses_an_unknown_key():
    with pytest.raises(PayloadInvalid):
        DEFAULT_EVENT_TYPES.validate(
            PLAYTHROUGH_CREATED.event_type,
            {
                "player_game": str(uuid.uuid7()),
                "kind": "ordinary",
                "note": "",
            },
        )


def test_the_payload_refuses_a_kind_nobody_defined():
    with pytest.raises(PayloadInvalid):
        DEFAULT_EVENT_TYPES.validate(
            PLAYTHROUGH_CREATED.event_type,
            {"player_game": str(uuid.uuid7()), "kind": "speedrun"},
        )


def test_the_payload_refuses_a_reference_that_is_not_canonical_uuidv7():
    with pytest.raises(PayloadInvalid):
        DEFAULT_EVENT_TYPES.validate(
            PLAYTHROUGH_CREATED.event_type,
            {"player_game": str(uuid.uuid4()), "kind": "ordinary"},
        )


def test_the_builder_mints_a_fresh_identity_each_call():
    tracked_id = uuid.uuid7()

    first = playthrough_created(tracked_id)
    second = playthrough_created(tracked_id)

    assert first.aggregate_id != second.aggregate_id
    assert first.payload == {"player_game": str(tracked_id), "kind": "ordinary"}


def test_the_endpoint_events_are_in_the_default_vocabulary():
    started = DEFAULT_EVENT_TYPES.spec_for("library.playthrough.started")
    completed = DEFAULT_EVENT_TYPES.spec_for("library.playthrough.completed")

    assert (started, completed) == (PLAYTHROUGH_STARTED, PLAYTHROUGH_COMPLETED)
    assert started.aggregate_type == "playthrough"
    assert completed.aggregate_type == "playthrough"


def test_an_endpoint_payload_carries_a_note_and_nothing_else():
    validated = DEFAULT_EVENT_TYPES.validate(
        PLAYTHROUGH_STARTED.event_type, {"note": "blind run"}
    )

    assert validated == {"note": "blind run"}


def test_an_endpoint_payload_takes_the_empty_note():
    """No note is the empty string, never an absent key."""
    assert DEFAULT_EVENT_TYPES.validate(
        PLAYTHROUGH_COMPLETED.event_type, {"note": ""}
    ) == {"note": ""}


def test_an_endpoint_payload_refuses_a_missing_note():
    with pytest.raises(PayloadInvalid):
        DEFAULT_EVENT_TYPES.validate(PLAYTHROUGH_STARTED.event_type, {})


def test_an_endpoint_payload_refuses_a_date_of_its_own():
    """The date rides in effective_time, and has one home."""
    with pytest.raises(PayloadInvalid):
        DEFAULT_EVENT_TYPES.validate(
            PLAYTHROUGH_STARTED.event_type, {"note": "", "when": "2024-03"}
        )


def test_the_endpoint_builders_name_the_playthrough_they_are_told_about():
    """The aggregate exists, so nothing mints an identity here."""
    identity = uuid.uuid7()
    when = TemporalValue.from_month(2024, 3)

    started = playthrough_started(identity, when=when, note="blind run")
    completed = playthrough_completed(identity, when=None, note="")

    assert (started.aggregate_id, completed.aggregate_id) == (identity, identity)
    assert (started.effective_time, completed.effective_time) == (when, None)
    assert (started.payload, completed.payload) == ({"note": "blind run"}, {"note": ""})


def test_the_descriptive_events_are_in_the_default_vocabulary():
    name = DEFAULT_EVENT_TYPES.spec_for("library.playthrough.name_changed")
    note = DEFAULT_EVENT_TYPES.spec_for("library.playthrough.note_changed")

    assert (name, note) == (PLAYTHROUGH_NAME_CHANGED, PLAYTHROUGH_NOTE_CHANGED)
    assert (name.aggregate_type, note.aggregate_type) == ("playthrough", "playthrough")


def test_a_descriptive_payload_refuses_the_other_one_s_key():
    """Two facts, two types, and neither reads the other."""
    with pytest.raises(PayloadInvalid):
        DEFAULT_EVENT_TYPES.validate(
            PLAYTHROUGH_NAME_CHANGED.event_type, {"note": "second run"}
        )
    with pytest.raises(PayloadInvalid):
        DEFAULT_EVENT_TYPES.validate(
            PLAYTHROUGH_NOTE_CHANGED.event_type, {"name": "Ironman"}
        )


def test_a_descriptive_payload_takes_the_cleared_value():
    """A blank name reads as the run's number."""
    assert DEFAULT_EVENT_TYPES.validate(
        PLAYTHROUGH_NAME_CHANGED.event_type, {"name": ""}
    ) == {"name": ""}


def test_the_descriptive_events_state_no_day():
    """A name is true of the run, not of a date."""
    identity = uuid.uuid7()

    renamed = playthrough_name_changed(identity, name="Ironman")
    noted = playthrough_note_changed(identity, note="no saves")

    assert (renamed.aggregate_id, noted.aggregate_id) == (identity, identity)
    assert (renamed.effective_time, noted.effective_time) == (None, None)
    assert (renamed.payload, noted.payload) == (
        {"name": "Ironman"},
        {"note": "no saves"},
    )
