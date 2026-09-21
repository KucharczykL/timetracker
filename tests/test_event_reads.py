"""Reading one library's event stream by the batch that wrote it."""

import uuid
from datetime import date, timedelta

import pytest

from games.commands.playergame import TrackGame
from games.commands.playersession import CreateSession, DurationOnlyTiming
from games.commands.session_reclassification import (
    ReclassifySessionAsHistoricalPlaytime,
    statement_from_session,
)
from games.events.dispatch import dispatch
from games.events.vocabulary import DEFAULT_EVENT_TYPES
from games.models import (
    Game,
    HistoricalPlaytime,
    PlayerSession,
    Playthrough,
)
from games.reads.events import aggregate_events, batch_aggregate_ids, batch_events

pytestmark = [pytest.mark.untracked_games, pytest.mark.django_db(transaction=True)]

A_DAY = date(2026, 3, 5)


@pytest.fixture(autouse=True)
def prague_calendar(owned_user, set_user_setting):
    set_user_setting(owned_user, "DISPLAY_TIME_ZONE", "Europe/Prague")


@pytest.fixture
def second_library(django_user_model):
    return django_user_model.objects.create_user(
        username="second-owner", password="p"
    ).library


def a_run(library, actor, name) -> Playthrough:
    game = Game.objects.create(library=library, name=name)
    dispatch(
        TrackGame(game_id=game.pk),
        actor=actor,
        library=library,
        idempotency_key=f"track-{game.pk}",
    )
    return Playthrough.objects.get(player_game__game=game)


def a_written_session(library, actor, run, day=A_DAY) -> PlayerSession:
    """One written-down session; its day tells it from its siblings."""
    dispatch(
        CreateSession(
            playthrough_id=run.pk,
            timing=DurationOnlyTiming(day=day, duration=timedelta(hours=9)),
        ),
        actor=actor,
        library=library,
        idempotency_key=str(uuid.uuid7()),
    )
    return PlayerSession.objects.get(playthrough=run, stated_day=day)


def convert(library, actor, session, correlation_id) -> HistoricalPlaytime:
    """One row of a batch: a record beside the session that became it."""
    dispatch(
        ReclassifySessionAsHistoricalPlaytime(
            session_id=session.pk, statement=statement_from_session(session)
        ),
        actor=actor,
        library=library,
        idempotency_key=str(uuid.uuid7()),
        correlation_id=correlation_id,
    )
    return HistoricalPlaytime.objects.get(reclassified_from=session)


def test_a_batch_answers_its_own_events_in_order(owned_user, owned_library):
    run = a_run(owned_library, owned_user, "Outer Wilds")
    correlation_id = uuid.uuid7()
    for offset in range(2):
        convert(
            owned_library,
            owned_user,
            a_written_session(
                owned_library, owned_user, run, A_DAY + timedelta(days=offset)
            ),
            correlation_id,
        )

    events = list(batch_events(owned_library, correlation_id))

    assert [event.sequence for event in events] == sorted(
        event.sequence for event in events
    )
    assert {event.correlation_id for event in events} == {correlation_id}


def test_a_batch_never_reaches_another_library(
    owned_user, owned_library, second_library
):
    """One correlation id in two libraries is two batches."""
    correlation_id = uuid.uuid7()
    convert(
        owned_library,
        owned_user,
        a_written_session(
            owned_library, owned_user, a_run(owned_library, owned_user, "Outer Wilds")
        ),
        correlation_id,
    )
    stranger = second_library.user
    convert(
        second_library,
        stranger,
        a_written_session(
            second_library, stranger, a_run(second_library, stranger, "Celeste")
        ),
        correlation_id,
    )

    ours = set(batch_events(owned_library, correlation_id).values_list("id", flat=True))
    theirs = set(
        batch_events(second_library, correlation_id).values_list("id", flat=True)
    )

    assert ours and theirs
    assert not ours & theirs


def test_a_batch_names_the_sessions_and_not_the_records(owned_user, owned_library):
    """The reclassification writes two aggregates under one correlation.

    Its inverse takes a session, so a read that answered both would hand
    a record's key to a command that reads sessions.
    """
    run = a_run(owned_library, owned_user, "Outer Wilds")
    correlation_id = uuid.uuid7()
    sessions = [
        a_written_session(
            owned_library, owned_user, run, A_DAY + timedelta(days=offset)
        )
        for offset in range(2)
    ]
    records = [
        convert(owned_library, owned_user, session, correlation_id)
        for session in sessions
    ]

    named = batch_aggregate_ids(owned_library, correlation_id, "playersession")

    assert set(named) == {session.pk for session in sessions}
    assert not set(named) & {record.pk for record in records}


def test_a_batch_names_each_row_once(owned_user, owned_library):
    run = a_run(owned_library, owned_user, "Outer Wilds")
    correlation_id = uuid.uuid7()
    session = a_written_session(owned_library, owned_user, run)
    convert(owned_library, owned_user, session, correlation_id)

    named = batch_aggregate_ids(owned_library, correlation_id, "playersession")

    assert named == [session.pk]


def test_an_aggregate_type_names_its_own_event_types():
    playersession = DEFAULT_EVENT_TYPES.event_types_for("playersession")

    assert "library.playersession.reclassified" in playersession
    assert "library.historicalplaytime.created" not in playersession


def test_an_unknown_aggregate_type_names_nothing():
    assert DEFAULT_EVENT_TYPES.event_types_for("nothing") == frozenset()


def test_one_aggregate_answers_its_own_events_in_sequence_order(
    owned_user, owned_library
):
    run = a_run(owned_library, owned_user, "Outer Wilds")
    session = a_written_session(owned_library, owned_user, run)
    convert(owned_library, owned_user, session, uuid.uuid7())

    events = list(aggregate_events(owned_library, session.pk))

    assert [event.sequence for event in events] == sorted(
        event.sequence for event in events
    )
    assert {event.aggregate_id for event in events} == {session.pk}
    assert len(events) > 1


def test_one_aggregate_never_answers_another_row(owned_user, owned_library):
    run = a_run(owned_library, owned_user, "Outer Wilds")
    mine = a_written_session(owned_library, owned_user, run)
    a_written_session(owned_library, owned_user, run, A_DAY + timedelta(days=1))

    assert {
        event.aggregate_id for event in aggregate_events(owned_library, mine.pk)
    } == {mine.pk}


def test_one_aggregate_never_reaches_another_library(
    owned_user, owned_library, second_library
):
    session = a_written_session(
        owned_library, owned_user, a_run(owned_library, owned_user, "Outer Wilds")
    )

    assert not aggregate_events(second_library, session.pk).exists()
