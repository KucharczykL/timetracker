"""Turning a session into a historical playtime record."""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from django.utils import timezone

from games.commands.historical_playtime import (
    ONE_GAME,
    SESSION_STILL_LIVE,
    RemoveHistoricalPlaytime,
    RestoreHistoricalPlaytime,
)
from games.commands.playergame import RemovePlayerGame, TrackGame
from games.commands.playersession import (
    RECORD_STILL_LIVE,
    CorrectedTiming,
    CreateSession,
    DurationOnlyTiming,
    RemoveSession,
    RestoreSession,
    TimedTiming,
)
from games.commands.playthrough import CreatePlaythrough
from games.commands.session_reclassification import (
    ANOTHER_GAME,
    NEVER_RECLASSIFIED,
    STILL_RUNNING,
    ReclassifySessionAsHistoricalPlaytime,
    UndoSessionReclassification,
    statement_from_session,
)
from games.events.dispatch import CommandOutcome, CommandRejected, dispatch
from games.models import (
    Device,
    Game,
    HistoricalPlaytime,
    HistoricalPlaytimeProvenance,
    LibraryEvent,
    PlayerSession,
    Playthrough,
)
from games.reads.playthrough_activity import RunActivity

pytestmark = [pytest.mark.untracked_games, pytest.mark.django_db(transaction=True)]

START = datetime(2026, 1, 1, 23, 30, tzinfo=UTC)
A_DAY = date(2026, 3, 5)
AN_HOUR = timedelta(hours=1)


@pytest.fixture(autouse=True)
def prague_calendar(owned_user, set_user_setting):
    set_user_setting(owned_user, "DISPLAY_TIME_ZONE", "Europe/Prague")


@pytest.fixture
def game(owned_library):
    return Game.objects.create(library=owned_library, name="Outer Wilds")


@pytest.fixture
def run(owned_user, owned_library, game) -> Playthrough:
    dispatch(
        TrackGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="track",
    )
    return Playthrough.objects.get(player_game__game=game)


@pytest.fixture
def second_run(owned_user, owned_library, run) -> Playthrough:
    dispatch(
        CreatePlaythrough(game_id=run.player_game.game_id),
        actor=owned_user,
        library=owned_library,
        idempotency_key="second",
    )
    return Playthrough.objects.exclude(pk=run.pk).get()


@pytest.fixture
def other_game_run(owned_user, owned_library) -> Playthrough:
    other = Game.objects.create(library=owned_library, name="Celeste")
    dispatch(
        TrackGame(game_id=other.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="track-other",
    )
    return Playthrough.objects.get(player_game__game=other)


def a_session(library, actor, run, timing, *, key=None, **stated) -> PlayerSession:
    dispatch(
        CreateSession(playthrough_id=run.pk, timing=timing, **stated),
        actor=actor,
        library=library,
        idempotency_key=key or str(uuid.uuid7()),
    )
    return PlayerSession.objects.get(playthrough=run)


def a_duration_only(library, actor, run, **stated) -> PlayerSession:
    return a_session(
        library,
        actor,
        run,
        DurationOnlyTiming(day=A_DAY, duration=timedelta(hours=9)),
        **stated,
    )


def convert(library, actor, session, statement=None, *, key=None) -> HistoricalPlaytime:
    dispatch(
        ReclassifySessionAsHistoricalPlaytime(
            session_id=session.pk,
            statement=statement or statement_from_session(session),
        ),
        actor=actor,
        library=library,
        idempotency_key=key or str(uuid.uuid7()),
    )
    return HistoricalPlaytime.objects.get()


def refused(library, actor, command) -> CommandRejected:
    with pytest.raises(CommandRejected) as refusal:
        dispatch(
            command, actor=actor, library=library, idempotency_key=str(uuid.uuid7())
        )
    assert refusal.value.sentence
    return refusal.value


# --- The statement a session states ------------------------------------------


def test_the_statement_reads_the_session(owned_user, owned_library, run):
    device = Device.objects.create(library=owned_library, name="Steam Deck")
    session = a_duration_only(
        owned_library, owned_user, run, device_id=device.pk, note="from a screenshot"
    )

    statement = statement_from_session(session)

    assert statement.duration == session.effective_duration
    assert statement.when == "2026-03-05"
    assert statement.playthrough_ids == (run.pk,)
    assert statement.device_id == device.pk
    assert statement.emulated is False
    assert statement.note == "from a screenshot"
    assert statement.provenance == HistoricalPlaytimeProvenance.MANUALLY_ENTERED


def test_the_statement_takes_the_provenance_the_caller_states(
    owned_user, owned_library, run
):
    session = a_duration_only(owned_library, owned_user, run)

    statement = statement_from_session(session, HistoricalPlaytimeProvenance.ESTIMATED)

    assert statement.provenance == HistoricalPlaytimeProvenance.ESTIMATED


# --- The act ------------------------------------------------------------------


def test_one_act_answers_both_events(owned_user, owned_library, run):
    session = a_duration_only(owned_library, owned_user, run)

    record = convert(owned_library, owned_user, session)

    appended = list(
        LibraryEvent.objects.filter(
            library=owned_library,
            event_type__in=(
                "library.historicalplaytime.created",
                "library.playersession.reclassified",
            ),
        ).order_by("sequence")
    )
    assert [event.event_type for event in appended] == [
        "library.historicalplaytime.created",
        "library.playersession.reclassified",
    ]
    assert len({event.correlation_id for event in appended}) == 1
    assert appended[1].payload == {"record": str(record.pk)}


def test_the_record_states_what_the_session_stated(owned_user, owned_library, run):
    session = a_duration_only(owned_library, owned_user, run, note="a guess")

    record = convert(owned_library, owned_user, session)

    assert record.duration == session.effective_duration
    assert record.when.canonical == "2026-03-05"
    assert record.player_game_id == run.player_game_id
    assert record.note == "a guess"
    assert set(record.runs.values_list("playthrough_id", flat=True)) == {run.pk}


def test_the_session_is_marked_and_names_the_record(owned_user, owned_library, run):
    session = a_duration_only(owned_library, owned_user, run)

    record = convert(owned_library, owned_user, session)

    session.refresh_from_db()
    assert session.removed_at is not None
    assert session.reclassified_into_id == record.pk
    assert not PlayerSession.objects.alive().exists()


def test_a_running_timed_session_is_refused(owned_user, owned_library, run):
    """A running row measures nothing; state a duration."""
    session = a_session(
        owned_library,
        owned_user,
        run,
        TimedTiming(started_at=START, day_zone="Europe/Prague"),
    )
    stated = statement_from_session(session)._replace(duration=AN_HOUR)

    refusal = refused(
        owned_library,
        owned_user,
        ReclassifySessionAsHistoricalPlaytime(session_id=session.pk, statement=stated),
    )

    assert refusal.sentence == STILL_RUNNING
    assert not HistoricalPlaytime.objects.exists()


def test_a_finished_timed_session_is_admitted(owned_user, owned_library, run):
    """The command's rule; the screen is what narrows it."""
    session = a_session(
        owned_library,
        owned_user,
        run,
        TimedTiming(
            started_at=START, ended_at=START + AN_HOUR, day_zone="Europe/Prague"
        ),
    )

    record = convert(owned_library, owned_user, session)

    assert record.duration == AN_HOUR


def test_a_corrected_session_is_admitted(owned_user, owned_library, run):
    session = a_session(
        owned_library,
        owned_user,
        run,
        CorrectedTiming(
            started_at=START,
            ended_at=START + AN_HOUR,
            duration=timedelta(minutes=20),
            day_zone="Europe/Prague",
        ),
    )

    assert convert(owned_library, owned_user, session).duration == timedelta(minutes=20)


def test_a_run_of_another_game_is_refused(
    owned_user, owned_library, run, other_game_run
):
    session = a_duration_only(owned_library, owned_user, run)
    elsewhere = statement_from_session(session)._replace(
        playthrough_ids=(other_game_run.pk,)
    )

    refusal = refused(
        owned_library,
        owned_user,
        ReclassifySessionAsHistoricalPlaytime(
            session_id=session.pk, statement=elsewhere
        ),
    )

    assert refusal.sentence == ANOTHER_GAME


def test_two_games_are_refused_before_the_session_is_read(
    owned_user, owned_library, run, other_game_run
):
    session = a_duration_only(owned_library, owned_user, run)
    both = statement_from_session(session)._replace(
        playthrough_ids=(run.pk, other_game_run.pk)
    )

    refusal = refused(
        owned_library,
        owned_user,
        ReclassifySessionAsHistoricalPlaytime(session_id=session.pk, statement=both),
    )

    assert refusal.sentence == ONE_GAME


def test_a_sibling_run_of_the_same_game_is_admitted(
    owned_user, owned_library, run, second_run
):
    session = a_duration_only(owned_library, owned_user, run)
    both = statement_from_session(session)._replace(
        playthrough_ids=(run.pk, second_run.pk)
    )

    record = convert(owned_library, owned_user, session, both)

    assert set(record.runs.values_list("playthrough_id", flat=True)) == {
        run.pk,
        second_run.pk,
    }


def test_a_session_holding_a_removed_device_still_converts(
    owned_user, owned_library, run
):
    """91 of 93 rows name a device."""
    device = Device.objects.create(library=owned_library, name="Vita")
    session = a_duration_only(owned_library, owned_user, run, device_id=device.pk)
    Device.objects.filter(pk=device.pk).update(removed_at=timezone.now())

    record = convert(owned_library, owned_user, session)

    assert record.device_id == device.pk


def test_a_removed_device_named_anew_is_refused(owned_user, owned_library, run):
    device = Device.objects.create(library=owned_library, name="Vita")
    other = Device.objects.create(library=owned_library, name="PSP")
    session = a_duration_only(owned_library, owned_user, run, device_id=device.pk)
    Device.objects.filter(pk=other.pk).update(removed_at=timezone.now())
    swapped = statement_from_session(session)._replace(device_id=other.pk)

    refusal = refused(
        owned_library,
        owned_user,
        ReclassifySessionAsHistoricalPlaytime(session_id=session.pk, statement=swapped),
    )

    assert refusal.sentence


def test_the_same_key_twice_appends_one_pair(owned_user, owned_library, run):
    session = a_duration_only(owned_library, owned_user, run)
    statement = statement_from_session(session)

    for _ in range(2):
        dispatch(
            ReclassifySessionAsHistoricalPlaytime(
                session_id=session.pk, statement=statement
            ),
            actor=owned_user,
            library=owned_library,
            idempotency_key="one-conversion",
        )

    assert HistoricalPlaytime.objects.count() == 1
    assert (
        LibraryEvent.objects.filter(
            event_type="library.playersession.reclassified"
        ).count()
        == 1
    )


def test_a_removed_session_is_refused(owned_user, owned_library, run):
    session = a_duration_only(owned_library, owned_user, run)
    statement = statement_from_session(session)
    dispatch(
        RemoveSession(session_id=session.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="gone",
    )

    refused(
        owned_library,
        owned_user,
        ReclassifySessionAsHistoricalPlaytime(
            session_id=session.pk, statement=statement
        ),
    )


def test_a_removed_run_is_refused(owned_user, owned_library, run, second_run):
    session = a_duration_only(owned_library, owned_user, second_run)
    statement = statement_from_session(session)
    #: Stamped: a run with sessions refuses removal.
    Playthrough.objects.filter(pk=second_run.pk).update(removed_at=timezone.now())

    refused(
        owned_library,
        owned_user,
        ReclassifySessionAsHistoricalPlaytime(
            session_id=session.pk, statement=statement
        ),
    )


def test_a_removed_game_is_refused(owned_user, owned_library, run, game):
    session = a_duration_only(owned_library, owned_user, run)
    statement = statement_from_session(session)
    PlayerSession.objects.filter(pk=session.pk).update(removed_at=timezone.now())
    dispatch(
        RemovePlayerGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="game-gone",
    )
    PlayerSession.objects.filter(pk=session.pk).update(removed_at=None)

    refused(
        owned_library,
        owned_user,
        ReclassifySessionAsHistoricalPlaytime(
            session_id=session.pk, statement=statement
        ),
    )


# --- What moves ---------------------------------------------------------------


def test_the_playtime_total_does_not_move(owned_user, owned_library, run, game):
    from games.reads.playtime import game_playtime

    session = a_duration_only(owned_library, owned_user, run)
    before = game_playtime(owned_library, game)

    convert(owned_library, owned_user, session)

    assert game_playtime(owned_library, game).total == before.total


def test_the_session_count_falls_by_one(owned_user, owned_library, run):
    from games.reads.player_sessions import library_sessions

    session = a_duration_only(owned_library, owned_user, run)
    before = library_sessions(owned_library).count()

    convert(owned_library, owned_user, session)

    assert library_sessions(owned_library).count() == before - 1


def test_the_run_reads_never_played(owned_user, owned_library, run):
    """The figure a person sees, on Game detail and in the facet."""
    from games.reads.playthrough_runs import runs_with_condition

    session = a_duration_only(owned_library, owned_user, run)

    convert(owned_library, owned_user, session)

    assert (
        runs_with_condition(owned_library).get(pk=run.pk).activity
        == RunActivity.NEVER_PLAYED
    )


# --- The undo -----------------------------------------------------------------


def undo(library, actor, session, *, key=None) -> None:
    dispatch(
        UndoSessionReclassification(session_id=session.pk),
        actor=actor,
        library=library,
        idempotency_key=key or str(uuid.uuid7()),
    )


def test_the_undo_reverses_the_pair(owned_user, owned_library, run):
    session = a_duration_only(owned_library, owned_user, run)
    record = convert(owned_library, owned_user, session)

    undo(owned_library, owned_user, session)

    record.refresh_from_db()
    session.refresh_from_db()
    assert record.removed_at is not None
    assert session.removed_at is None
    assert session.reclassified_into_id == record.pk
    appended = list(
        LibraryEvent.objects.filter(
            event_type__in=(
                "library.historicalplaytime.removed",
                "library.playersession.restored",
            )
        ).order_by("sequence")
    )
    assert [event.event_type for event in appended] == [
        "library.historicalplaytime.removed",
        "library.playersession.restored",
    ]
    assert len({event.correlation_id for event in appended}) == 1


def test_a_second_undo_records_nothing(owned_user, owned_library, run):
    session = a_duration_only(owned_library, owned_user, run)
    convert(owned_library, owned_user, session)
    undo(owned_library, owned_user, session)
    before = LibraryEvent.objects.count()

    undo(owned_library, owned_user, session)

    assert LibraryEvent.objects.count() == before


def test_a_session_that_became_no_record_is_refused(owned_user, owned_library, run):
    session = a_duration_only(owned_library, owned_user, run)

    refusal = refused(
        owned_library, owned_user, UndoSessionReclassification(session_id=session.pk)
    )

    assert refusal.sentence == NEVER_RECLASSIFIED


def test_the_undo_returns_a_session_whose_record_was_already_removed(
    owned_user, owned_library, run
):
    """Only the leg still to happen."""
    session = a_duration_only(owned_library, owned_user, run)
    record = convert(owned_library, owned_user, session)
    dispatch(
        RemoveHistoricalPlaytime(record_id=record.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="record-gone",
    )
    before = LibraryEvent.objects.count()

    undo(owned_library, owned_user, session)

    session.refresh_from_db()
    assert session.removed_at is None
    assert LibraryEvent.objects.count() == before + 1


# --- The two guards -----------------------------------------------------------


def test_a_restore_alone_is_refused_while_the_record_is_live(
    owned_user, owned_library, run
):
    session = a_duration_only(owned_library, owned_user, run)
    record = convert(owned_library, owned_user, session)

    refusal = refused(owned_library, owned_user, RestoreSession(session_id=session.pk))

    assert refusal.sentence == RECORD_STILL_LIVE
    assert str(record.pk) in refusal.args[0]


def test_a_restore_alone_is_admitted_once_the_record_is_removed(
    owned_user, owned_library, run
):
    session = a_duration_only(owned_library, owned_user, run)
    record = convert(owned_library, owned_user, session)
    dispatch(
        RemoveHistoricalPlaytime(record_id=record.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="record-gone",
    )

    dispatch(
        RestoreSession(session_id=session.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="back",
    )

    session.refresh_from_db()
    assert session.removed_at is None


def test_a_record_restore_is_refused_while_its_session_is_live(
    owned_user, owned_library, run
):
    session = a_duration_only(owned_library, owned_user, run)
    record = convert(owned_library, owned_user, session)
    undo(owned_library, owned_user, session)

    refusal = refused(
        owned_library, owned_user, RestoreHistoricalPlaytime(record_id=record.pk)
    )

    assert refusal.sentence == SESSION_STILL_LIVE


def test_a_live_session_still_answers_unchanged(owned_user, owned_library, run):
    """The no-op comes first, before the new refusal."""
    session = a_duration_only(owned_library, owned_user, run)
    before = LibraryEvent.objects.count()

    result = dispatch(
        RestoreSession(session_id=session.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="nothing-to-do",
    )

    assert result.outcome is CommandOutcome.UNCHANGED
    assert LibraryEvent.objects.count() == before
