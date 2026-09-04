"""What a library records about a run at a game."""

import uuid
from typing import get_args

import pytest

from games.events.playthrough import (
    PLAYTHROUGH_CREATED,
    PlaythroughKindValue,
    playthrough_created,
)
from games.events.vocabulary import DEFAULT_EVENT_TYPES, PayloadInvalid
from games.models import PlaythroughKind

pytestmark = pytest.mark.untracked_games


def test_the_creation_event_is_in_the_default_vocabulary():
    registered = DEFAULT_EVENT_TYPES.spec_for("library.playthrough.created")

    assert registered is PLAYTHROUGH_CREATED
    assert registered.aggregate_type == "playthrough"


def test_the_kind_literal_matches_the_choices():
    """A payload is read back as a plain string."""
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
