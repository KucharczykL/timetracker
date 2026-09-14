"""What a library records about one session."""

import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from games.events.idempotency import _canonical_datetime
from games.events.playersession import (
    PLAYERSESSION_CREATED,
    PLAYERSESSION_DEVICE_CHANGED,
    PLAYERSESSION_EMULATED_CHANGED,
    PLAYERSESSION_ENDED,
    PLAYERSESSION_MOVED,
    PLAYERSESSION_NOTE_CHANGED,
    PLAYERSESSION_TIMING_CORRECTED,
    TimedTimingPayload,
    canonical_day_text,
    canonical_instant_text,
    day_from_text,
    day_text,
    instant_from_text,
    instant_text,
    playersession_created,
    playersession_device_changed,
    playersession_emulated_changed,
    playersession_ended,
    playersession_moved,
    playersession_note_changed,
    playersession_timing_corrected,
)
from games.events.references import ReferenceArity
from games.events.vocabulary import DEFAULT_EVENT_TYPES, PayloadInvalid

RUN = uuid.uuid7()
DEVICE = {
    "kind": "device",
    "id": str(uuid.uuid7()),
    "label": "Steam Deck",
    "detail": "",
}


def a_timed_payload(**timing) -> dict:
    return {
        "playthrough": str(RUN),
        "device": None,
        "release": None,
        "timing": {
            "mode": "timed",
            "started_at": "2026-01-01T23:30:00+00:00",
            "started_at_zone": None,
            "ended_at": None,
            "ended_at_zone": None,
            "day_zone": "Europe/Prague",
        }
        | timing,
        "note": "",
        "emulated": False,
    }


def validated(payload: dict) -> dict:
    return DEFAULT_EVENT_TYPES.validate(PLAYERSESSION_CREATED.event_type, payload)


def test_the_event_type_is_spelled_once_and_forever():
    assert PLAYERSESSION_CREATED.event_type == "library.playersession.created"
    assert PLAYERSESSION_CREATED.aggregate_type == "playersession"


def test_a_timed_payload_round_trips():
    payload = a_timed_payload()

    assert validated(payload) == payload


def test_a_duration_only_payload_round_trips():
    payload = a_timed_payload() | {
        "timing": {
            "mode": "duration_only",
            "stated_day": "2026-03-05",
            "duration_seconds": 5400,
        }
    }

    assert validated(payload) == payload


def test_a_corrected_payload_round_trips():
    payload = a_timed_payload() | {
        "timing": {
            "mode": "corrected",
            "started_at": "2026-01-01T20:00:00+00:00",
            "started_at_zone": "Europe/Prague",
            "ended_at": "2026-01-01T21:00:00+00:00",
            "ended_at_zone": "Europe/Prague",
            "day_zone": "Europe/Prague",
            "duration_seconds": 1800,
        }
    }

    assert validated(payload) == payload


def test_an_unknown_mode_is_refused():
    with pytest.raises(PayloadInvalid):
        validated(a_timed_payload() | {"timing": {"mode": "guessed"}})


def test_an_extra_key_is_refused():
    with pytest.raises(PayloadInvalid):
        validated(a_timed_payload(junk="x"))


def test_a_missing_key_is_refused():
    payload = a_timed_payload()
    del payload["timing"]["day_zone"]

    with pytest.raises(PayloadInvalid):
        validated(payload)


def test_a_lax_integer_is_refused():
    payload = a_timed_payload() | {
        "timing": {
            "mode": "duration_only",
            "stated_day": "2026-03-05",
            "duration_seconds": "5400",
        }
    }

    with pytest.raises(PayloadInvalid):
        validated(payload)


def test_a_timed_payload_may_not_state_a_duration():
    with pytest.raises(PayloadInvalid):
        validated(a_timed_payload(duration_seconds=60))


@pytest.mark.parametrize(
    "spelling",
    [
        "2026-01-01T23:30:00Z",
        "2026-01-02T00:30:00+01:00",
        "2026-01-01 23:30:00+00:00",
        "not a date",
        "2026-01-01T23:30:00",
    ],
)
def test_a_non_canonical_instant_is_refused(spelling):
    with pytest.raises(PayloadInvalid):
        validated(a_timed_payload(started_at=spelling))


@pytest.mark.parametrize("spelling", ["2026-3-5", "05/03/2026", "2026-03-05T00:00:00"])
def test_a_non_canonical_day_is_refused(spelling):
    payload = a_timed_payload() | {
        "timing": {
            "mode": "duration_only",
            "stated_day": spelling,
            "duration_seconds": 5400,
        }
    }

    with pytest.raises(PayloadInvalid):
        validated(payload)


def test_an_instant_survives_the_round_trip_to_the_microsecond():
    stated = datetime(2026, 1, 1, 23, 30, 15, 123456, tzinfo=ZoneInfo("Asia/Tokyo"))

    assert instant_from_text(instant_text(stated)) == stated


def test_an_instant_is_written_in_one_zone():
    stated = datetime(2026, 1, 2, 8, 30, tzinfo=ZoneInfo("Asia/Tokyo"))

    assert instant_text(stated) == "2026-01-01T23:30:00+00:00"


def test_a_day_survives_the_round_trip():
    assert day_from_text(day_text(date(2026, 3, 5))) == date(2026, 3, 5)


def test_the_canonical_forms_answer_what_they_were_given():
    assert canonical_instant_text("2026-01-01T23:30:00+00:00") == (
        "2026-01-01T23:30:00+00:00"
    )
    assert canonical_day_text("2026-03-05") == "2026-03-05"


def test_the_references_are_enumerated():
    fields = DEFAULT_EVENT_TYPES.reference_fields_for(PLAYERSESSION_CREATED.event_type)

    assert fields == {
        "device": ReferenceArity.OPTIONAL,
        "release": ReferenceArity.OPTIONAL,
    }


def test_a_device_is_carried_as_a_reference():
    payload = a_timed_payload() | {"device": DEVICE}

    assert validated(payload)["device"] == DEVICE


def test_a_timed_session_takes_the_day_its_zone_reads():
    event = playersession_created(
        RUN,
        timing={
            "mode": "timed",
            "started_at": "2026-01-01T23:30:00+00:00",
            "started_at_zone": None,
            "ended_at": None,
            "ended_at_zone": None,
            "day_zone": "Europe/Prague",
        },
        device=None,
        release=None,
        note="",
        emulated=False,
    )

    #: Half past midnight in Prague.
    assert event.effective_time.canonical == "2026-01-02"


def test_a_duration_only_session_takes_its_written_day():
    event = playersession_created(
        RUN,
        timing={
            "mode": "duration_only",
            "stated_day": "2026-03-05",
            "duration_seconds": 5400,
        },
        device=None,
        release=None,
        note="",
        emulated=False,
    )

    assert event.effective_time.canonical == "2026-03-05"


def test_the_identity_may_be_stated():
    stated = uuid.uuid7()

    event = playersession_created(
        RUN,
        timing={
            "mode": "duration_only",
            "stated_day": "2026-03-05",
            "duration_seconds": 5400,
        },
        device=None,
        release=None,
        note="",
        emulated=False,
        session_id=stated,
    )

    assert event.aggregate_id == stated


def test_an_unstated_identity_is_minted():
    event = playersession_created(
        RUN,
        timing={
            "mode": "duration_only",
            "stated_day": "2026-03-05",
            "duration_seconds": 5400,
        },
        device=None,
        release=None,
        note="",
        emulated=False,
    )

    assert event.aggregate_id.version == 7


def test_a_duration_in_seconds_is_what_the_payload_carries():
    event = playersession_created(
        RUN,
        timing={
            "mode": "duration_only",
            "stated_day": "2026-03-05",
            "duration_seconds": int(timedelta(minutes=90).total_seconds()),
        },
        device=None,
        release=None,
        note="",
        emulated=False,
    )

    assert event.payload["timing"]["duration_seconds"] == 5400


def test_the_built_event_validates():
    event = playersession_created(
        RUN,
        timing={
            "mode": "timed",
            "started_at": instant_text(datetime(2026, 1, 1, 23, 30, tzinfo=UTC)),
            "started_at_zone": "Europe/Prague",
            "ended_at": None,
            "ended_at_zone": None,
            "day_zone": "Europe/Prague",
        },
        device=DEVICE,
        release=None,
        note="A note",
        emulated=True,
    )

    assert validated(event.payload) == event.payload


# --- The end of a running session --------------------------------------------

AN_END = {"ended_at": "2026-01-02T01:30:00+00:00", "ended_at_zone": "Europe/Prague"}


def validated_end(payload: dict) -> dict:
    return DEFAULT_EVENT_TYPES.validate(PLAYERSESSION_ENDED.event_type, payload)


def test_the_end_event_type_is_spelled_once_and_forever():
    assert PLAYERSESSION_ENDED.event_type == "library.playersession.ended"
    assert PLAYERSESSION_ENDED.aggregate_type == "playersession"


def test_an_end_payload_round_trips():
    assert validated_end(AN_END) == AN_END


def test_an_end_may_state_no_zone():
    payload = AN_END | {"ended_at_zone": None}

    assert validated_end(payload) == payload


def test_an_end_payload_refuses_a_second_spelling_of_the_day_zone():
    with pytest.raises(PayloadInvalid):
        validated_end(AN_END | {"day_zone": "Europe/Prague"})


def test_an_end_payload_refuses_a_non_canonical_instant():
    with pytest.raises(PayloadInvalid):
        validated_end(AN_END | {"ended_at": "2026-01-02T01:30:00Z"})


def test_an_end_payload_refuses_a_missing_instant():
    with pytest.raises(PayloadInvalid):
        validated_end({"ended_at_zone": None})


def test_an_end_names_no_references():
    fields = DEFAULT_EVENT_TYPES.reference_fields_for(PLAYERSESSION_ENDED.event_type)

    assert fields == {}


def test_an_end_is_about_the_session_the_caller_names():
    session_id = uuid.uuid7()

    event = playersession_ended(
        session_id,
        ended_at=datetime(2026, 1, 1, 23, 30, tzinfo=UTC),
        ended_at_zone=None,
        day_zone=ZoneInfo("Europe/Prague"),
    )

    assert event.aggregate_id == session_id


def test_an_end_takes_the_day_its_zone_reads():
    event = playersession_ended(
        uuid.uuid7(),
        ended_at=datetime(2026, 1, 1, 23, 30, tzinfo=UTC),
        ended_at_zone=None,
        day_zone=ZoneInfo("Europe/Prague"),
    )

    #: Half past midnight in Prague.
    assert event.effective_time.canonical == "2026-01-02"


def test_an_end_may_land_on_a_later_day_than_the_creation_did():
    """The event dates the act, not the session."""
    session_id = uuid.uuid7()

    created = playersession_created(
        RUN,
        timing={
            "mode": "timed",
            "started_at": "2026-01-01T22:00:00+00:00",
            "started_at_zone": None,
            "ended_at": None,
            "ended_at_zone": None,
            "day_zone": "Europe/Prague",
        },
        device=None,
        release=None,
        note="",
        emulated=False,
        session_id=session_id,
    )
    ended = playersession_ended(
        session_id,
        ended_at=datetime(2026, 1, 2, 1, 0, tzinfo=UTC),
        ended_at_zone=None,
        day_zone=ZoneInfo("Europe/Prague"),
    )

    assert created.effective_time.canonical == "2026-01-01"
    assert ended.effective_time.canonical == "2026-01-02"


def test_the_built_end_validates():
    event = playersession_ended(
        uuid.uuid7(),
        ended_at=datetime(2026, 1, 2, 1, 30, tzinfo=UTC),
        ended_at_zone="Europe/Prague",
        day_zone=ZoneInfo("Europe/Prague"),
    )

    assert validated_end(event.payload) == event.payload


def test_the_payload_and_the_fingerprint_spell_an_instant_alike():
    """An end fingerprints safely because these agree.

    They are independently written expressions. Truncate either and
    every honest retry of one statement answers a conflict, with
    nothing else failing.
    """
    stated = datetime(2026, 1, 1, 23, 30, 15, 123456, tzinfo=ZoneInfo("Asia/Tokyo"))

    assert instant_text(stated) == _canonical_datetime(stated)


# --- Corrections -------------------------------------------------------------

SESSION = uuid.uuid7()

A_TIMED_TIMING: TimedTimingPayload = {
    "mode": "timed",
    "started_at": "2026-01-01T23:30:00+00:00",
    "started_at_zone": None,
    "ended_at": None,
    "ended_at_zone": None,
    "day_zone": "Europe/Prague",
}
A_DURATION_ONLY_TIMING = {
    "mode": "duration_only",
    "stated_day": "2026-03-05",
    "duration_seconds": 5400,
}
A_CORRECTED_TIMING = {
    "mode": "corrected",
    "started_at": "2026-01-01T22:30:00+00:00",
    "started_at_zone": "Europe/Prague",
    "ended_at": "2026-01-01T23:30:00+00:00",
    "ended_at_zone": "Europe/Prague",
    "day_zone": "Europe/Prague",
    "duration_seconds": 1800,
}


def validated_as(spec, payload: dict) -> dict:
    return DEFAULT_EVENT_TYPES.validate(spec.event_type, payload)


@pytest.mark.parametrize(
    ("spec", "event_type"),
    [
        (PLAYERSESSION_TIMING_CORRECTED, "library.playersession.timing_corrected"),
        (PLAYERSESSION_NOTE_CHANGED, "library.playersession.note_changed"),
        (PLAYERSESSION_DEVICE_CHANGED, "library.playersession.device_changed"),
        (PLAYERSESSION_EMULATED_CHANGED, "library.playersession.emulated_changed"),
        (PLAYERSESSION_MOVED, "library.playersession.moved"),
    ],
)
def test_each_correction_type_is_spelled_once_and_forever(spec, event_type):
    assert spec.event_type == event_type
    assert spec.aggregate_type == "playersession"


@pytest.mark.parametrize(
    "timing", [A_TIMED_TIMING, A_DURATION_ONLY_TIMING, A_CORRECTED_TIMING]
)
def test_a_timing_correction_carries_every_mode(timing):
    payload = {"timing": timing}

    assert validated_as(PLAYERSESSION_TIMING_CORRECTED, payload) == payload


def test_a_timing_correction_refuses_a_key_beside_the_statement():
    with pytest.raises(PayloadInvalid):
        validated_as(
            PLAYERSESSION_TIMING_CORRECTED, {"timing": A_TIMED_TIMING, "note": ""}
        )


def test_a_timing_correction_refuses_a_non_canonical_instant():
    timing = A_TIMED_TIMING | {"started_at": "2026-01-01T23:30:00Z"}

    with pytest.raises(PayloadInvalid):
        validated_as(PLAYERSESSION_TIMING_CORRECTED, {"timing": timing})


def test_an_empty_note_is_a_note():
    payload = {"note": ""}

    assert validated_as(PLAYERSESSION_NOTE_CHANGED, payload) == payload


def test_the_emulated_flag_is_strict():
    with pytest.raises(PayloadInvalid):
        validated_as(PLAYERSESSION_EMULATED_CHANGED, {"emulated": "true"})


@pytest.mark.parametrize("device", [None, DEVICE])
def test_a_device_change_round_trips(device):
    payload = {"device": device}

    assert validated_as(PLAYERSESSION_DEVICE_CHANGED, payload) == payload


def test_a_device_change_names_its_reference():
    fields = DEFAULT_EVENT_TYPES.reference_fields_for(
        PLAYERSESSION_DEVICE_CHANGED.event_type
    )

    assert fields == {"device": ReferenceArity.OPTIONAL}


def test_a_move_refuses_a_run_that_is_not_a_key():
    with pytest.raises(PayloadInvalid):
        validated_as(PLAYERSESSION_MOVED, {"playthrough": "run"})


def test_a_move_names_no_reference_kind():
    """A bare key, as the creation's run is."""
    assert (
        DEFAULT_EVENT_TYPES.reference_fields_for(PLAYERSESSION_MOVED.event_type) == {}
    )


def test_a_timing_correction_takes_the_day_its_zone_reads():
    event = playersession_timing_corrected(SESSION, timing=A_TIMED_TIMING)

    #: Half past midnight in Prague.
    assert event.effective_time.canonical == "2026-01-02"


def test_a_duration_only_correction_takes_its_written_day():
    event = playersession_timing_corrected(SESSION, timing=A_DURATION_ONLY_TIMING)

    assert event.effective_time.canonical == "2026-03-05"


def test_a_correction_is_dated_by_its_start_not_its_end():
    """A correction states the whole session again, so it dates the session."""
    timing = A_CORRECTED_TIMING | {
        "started_at": "2026-01-01T22:00:00+00:00",
        "ended_at": "2026-01-02T01:00:00+00:00",
    }

    event = playersession_timing_corrected(SESSION, timing=timing)

    assert event.effective_time.canonical == "2026-01-01"


@pytest.mark.parametrize(
    "event",
    [
        playersession_timing_corrected(SESSION, timing=A_TIMED_TIMING),
        playersession_note_changed(SESSION, note="played"),
        playersession_device_changed(SESSION, device=None),
        playersession_emulated_changed(SESSION, emulated=True),
        playersession_moved(SESSION, playthrough_id=RUN),
    ],
)
def test_every_correction_is_about_the_session_the_caller_names(event):
    assert event.aggregate_id == SESSION
    assert validated_as(event.spec, event.payload) == event.payload


@pytest.mark.parametrize(
    "event",
    [
        playersession_note_changed(SESSION, note="played"),
        playersession_device_changed(SESSION, device=None),
        playersession_emulated_changed(SESSION, emulated=True),
        playersession_moved(SESSION, playthrough_id=RUN),
    ],
)
def test_a_description_and_a_move_happen_on_no_day(event):
    assert event.effective_time is None


def test_a_move_carries_the_run_as_a_key():
    event = playersession_moved(SESSION, playthrough_id=RUN)

    assert event.payload == {"playthrough": str(RUN)}
