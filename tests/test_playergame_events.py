"""The event vocabulary for a tracked game."""

import uuid
from typing import get_args

import pytest

from games.events.playergame import (
    PLAYERGAME_ARCHIVED,
    PLAYERGAME_CREATED,
    PLAYERGAME_EXCLUDED_FROM_UNFINISHED_CHANGED,
    PLAYERGAME_MASTERED_CHANGED,
    PLAYERGAME_RESTORED,
    PLAYERGAME_STATUS_CHANGED,
    StatusValue,
)
from games.events.references import Reference, ReferenceArity
from games.events.vocabulary import DEFAULT_EVENT_TYPES, PayloadInvalid
from games.models import PlayerGameStatus

pytestmark = pytest.mark.untracked_games


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


def test_the_status_event_is_in_the_application_vocabulary():
    registered = DEFAULT_EVENT_TYPES.spec_for("library.playergame.status_changed")

    assert registered is PLAYERGAME_STATUS_CHANGED
    assert registered.aggregate_type == "playergame"


def test_the_status_payload_names_every_status():
    """The Literal and the choices agree."""
    #: __value__ reads through the PEP 695 alias.
    assert sorted(get_args(StatusValue.__value__)) == sorted(PlayerGameStatus.values)


def test_a_recorded_status_validates_as_the_plain_string_it_is_read_back_as():
    validated = DEFAULT_EVENT_TYPES.validate(
        PLAYERGAME_STATUS_CHANGED.event_type, {"status": "completed"}
    )

    assert validated == {"status": "completed"}


def test_a_status_outside_the_vocabulary_is_refused():
    with pytest.raises(PayloadInvalid):
        DEFAULT_EVENT_TYPES.validate(
            PLAYERGAME_STATUS_CHANGED.event_type, {"status": "finished"}
        )


def test_the_status_payload_carries_no_reference():
    """The creation event holds the one reference."""
    assert (
        DEFAULT_EVENT_TYPES.reference_fields_for(PLAYERGAME_STATUS_CHANGED.event_type)
        == {}
    )


def test_the_mastered_event_is_in_the_application_vocabulary():
    registered = DEFAULT_EVENT_TYPES.spec_for("library.playergame.mastered_changed")

    assert registered is PLAYERGAME_MASTERED_CHANGED
    assert registered.aggregate_type == "playergame"


def test_the_mastered_payload_states_the_value_it_sets():
    """One type states both directions."""
    validated = DEFAULT_EVENT_TYPES.validate(
        PLAYERGAME_MASTERED_CHANGED.event_type, {"mastered": False}
    )

    assert validated == {"mastered": False}


def test_a_mastered_payload_of_a_string_is_refused():
    """Strict validation takes no truthy string."""
    with pytest.raises(PayloadInvalid):
        DEFAULT_EVENT_TYPES.validate(
            PLAYERGAME_MASTERED_CHANGED.event_type, {"mastered": "true"}
        )


def test_a_mastered_payload_stating_nothing_is_refused():
    with pytest.raises(PayloadInvalid):
        DEFAULT_EVENT_TYPES.validate(PLAYERGAME_MASTERED_CHANGED.event_type, {})


def test_the_mastered_payload_carries_no_reference():
    """The creation event holds the one reference."""
    assert (
        DEFAULT_EVENT_TYPES.reference_fields_for(PLAYERGAME_MASTERED_CHANGED.event_type)
        == {}
    )


def test_the_exclusion_event_is_in_the_application_vocabulary():
    registered = DEFAULT_EVENT_TYPES.spec_for(
        "library.playergame.excluded_from_unfinished_changed"
    )

    assert registered is PLAYERGAME_EXCLUDED_FROM_UNFINISHED_CHANGED
    assert registered.aggregate_type == "playergame"


def test_the_exclusion_payload_states_the_value_it_sets():
    """One type states both directions."""
    validated = DEFAULT_EVENT_TYPES.validate(
        PLAYERGAME_EXCLUDED_FROM_UNFINISHED_CHANGED.event_type,
        {"excluded_from_unfinished": False},
    )

    assert validated == {"excluded_from_unfinished": False}


def test_an_exclusion_payload_of_a_string_is_refused():
    """Strict validation takes no truthy string."""
    with pytest.raises(PayloadInvalid):
        DEFAULT_EVENT_TYPES.validate(
            PLAYERGAME_EXCLUDED_FROM_UNFINISHED_CHANGED.event_type,
            {"excluded_from_unfinished": "true"},
        )


def test_an_exclusion_payload_stating_nothing_is_refused():
    with pytest.raises(PayloadInvalid):
        DEFAULT_EVENT_TYPES.validate(
            PLAYERGAME_EXCLUDED_FROM_UNFINISHED_CHANGED.event_type, {}
        )


def test_the_exclusion_payload_carries_no_reference():
    """The creation event holds the one reference."""
    assert (
        DEFAULT_EVENT_TYPES.reference_fields_for(
            PLAYERGAME_EXCLUDED_FROM_UNFINISHED_CHANGED.event_type
        )
        == {}
    )


def test_the_archive_event_is_in_the_application_vocabulary():
    registered = DEFAULT_EVENT_TYPES.spec_for("library.playergame.archived")

    assert registered is PLAYERGAME_ARCHIVED
    assert registered.aggregate_type == "playergame"


def test_the_archive_payload_states_nothing_but_its_type():
    """Two facts take two types, so no key states a direction."""
    assert DEFAULT_EVENT_TYPES.validate(PLAYERGAME_ARCHIVED.event_type, {}) == {}


def test_an_archive_payload_stating_a_direction_is_refused():
    """A key nobody declared could disagree with the type."""
    with pytest.raises(PayloadInvalid):
        DEFAULT_EVENT_TYPES.validate(PLAYERGAME_ARCHIVED.event_type, {"archived": True})


def test_the_archive_payload_carries_no_reference():
    """The creation event holds the one reference."""
    assert (
        DEFAULT_EVENT_TYPES.reference_fields_for(PLAYERGAME_ARCHIVED.event_type) == {}
    )


def test_the_restore_event_is_in_the_application_vocabulary():
    registered = DEFAULT_EVENT_TYPES.spec_for("library.playergame.restored")

    assert registered is PLAYERGAME_RESTORED
    assert registered.aggregate_type == "playergame"


def test_the_restore_payload_states_nothing_but_its_type():
    assert DEFAULT_EVENT_TYPES.validate(PLAYERGAME_RESTORED.event_type, {}) == {}


def test_a_restore_payload_stating_a_direction_is_refused():
    with pytest.raises(PayloadInvalid):
        DEFAULT_EVENT_TYPES.validate(PLAYERGAME_RESTORED.event_type, {"restored": True})
