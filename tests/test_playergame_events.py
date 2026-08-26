"""The event vocabulary for a tracked game."""

import uuid

import pytest

from games.events.playergame import PLAYERGAME_CREATED
from games.events.references import Reference, ReferenceArity
from games.events.vocabulary import DEFAULT_EVENT_TYPES, PayloadInvalid


def a_game_reference() -> Reference:
    return Reference(
        kind="catalog.game",
        id=str(uuid.uuid7()),
        label="Outer Wilds",
        detail="2019",
    )


def test_the_creation_event_is_in_the_application_vocabulary():
    registered = DEFAULT_EVENT_TYPES.spec_for("library.playergame.created")

    assert registered is PLAYERGAME_CREATED
    assert registered.aggregate_type == "playergame"


def test_the_payload_declares_its_catalog_reference():
    #: This declaration is the reference index integration.
    assert DEFAULT_EVENT_TYPES.reference_fields_for(PLAYERGAME_CREATED.event_type) == {
        "game": ReferenceArity.SINGLE
    }


def test_a_payload_repeating_what_the_envelope_records_is_refused():
    with pytest.raises(PayloadInvalid):
        DEFAULT_EVENT_TYPES.validate(
            PLAYERGAME_CREATED.event_type,
            {"game": a_game_reference(), "library": str(uuid.uuid7())},
        )


def test_a_payload_naming_no_game_is_refused():
    with pytest.raises(PayloadInvalid):
        DEFAULT_EVENT_TYPES.validate(PLAYERGAME_CREATED.event_type, {})
