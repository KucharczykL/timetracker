"""The entry events: their words and their payloads."""

import uuid
from typing import get_args

import pytest

from games.events.libraryentry import (
    ENTRY_ACQUISITION_EVENTS,
    LIBRARYENTRY_CREATED,
    EntryAccessValue,
    EntryFormatValue,
)
from games.events.references import Reference
from games.events.vocabulary import DEFAULT_EVENT_TYPES, PayloadInvalid
from games.models import EntryAccess, EntryFormat


def test_the_payload_spells_every_stored_word():
    assert set(get_args(EntryAccessValue.__value__)) == set(EntryAccess.values)
    assert set(get_args(EntryFormatValue.__value__)) == set(EntryFormat.values)


def _created_payload(**changes) -> dict:
    return {
        "player_game": str(uuid.uuid7()),
        "release": Reference(
            kind="catalog.release", id=str(uuid.uuid7()), label="Tunic", detail=""
        ),
        "access": "owned",
        "format": "digital",
        "note": "",
        "acquisition_note": "",
    } | changes


def test_the_created_payload_validates_and_refuses_an_extra_key():
    created = LIBRARYENTRY_CREATED.event_type
    payload = _created_payload()
    assert DEFAULT_EVENT_TYPES.validate(created, payload) == payload
    with pytest.raises(PayloadInvalid):
        DEFAULT_EVENT_TYPES.validate(created, _created_payload(colour="black"))
    with pytest.raises(PayloadInvalid):
        DEFAULT_EVENT_TYPES.validate(created, _created_payload(access="stolen"))


def test_every_entry_event_is_registered():
    types = {
        "library.libraryentry.created",
        "library.libraryentry.access_changed",
        "library.libraryentry.format_changed",
        "library.libraryentry.note_changed",
        "library.libraryentry.release_changed",
        "library.libraryentry.acquisition_corrected",
        "library.libraryentry.removed",
        "library.libraryentry.restored",
    }
    for event_type in types:
        assert DEFAULT_EVENT_TYPES.spec_for(event_type).aggregate_type == "libraryentry"
    assert ENTRY_ACQUISITION_EVENTS.family == (
        "library.libraryentry.acquisition_corrected",
    )
