"""Recording one session against a stated run."""

import uuid
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache

import pytest
from django.utils import timezone

from games.commands import playersession as playersession_commands
from games.commands.playergame import TrackGame
from games.commands.playersession import (
    CorrectedTiming,
    CreateSession,
    DurationOnlyTiming,
    EndSession,
    TimedTiming,
)
from games.events.dispatch import (
    CommandOutcome,
    CommandRejected,
    dispatch,
)
from games.models import (
    Device,
    Game,
    LibraryEvent,
    PlayerGame,
    PlayerSession,
    PlayerSessionTimingMode,
    Playthrough,
)
from games.writes.answers import CommandFailed, answered

pytestmark = [pytest.mark.untracked_games, pytest.mark.django_db(transaction=True)]

START = datetime(2026, 1, 1, 23, 30, tzinfo=UTC)


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
def second_library(django_user_model):
    other = django_user_model.objects.create_user(username="second-owner")
    return other.library


A_TIMED = TimedTiming(started_at=START, day_zone="Europe/Prague")

A_DURATION_ONLY = DurationOnlyTiming(
    day=date(2026, 3, 5), duration=timedelta(minutes=90)
)

A_CORRECTED = CorrectedTiming(
    started_at=START,
    ended_at=START + timedelta(hours=1),
    duration=timedelta(minutes=30),
    day_zone="Europe/Prague",
)


def a_timed(**stated) -> TimedTiming:
    return A_TIMED._replace(**stated)


def a_duration_only(**stated) -> DurationOnlyTiming:
    return A_DURATION_ONLY._replace(**stated)


def a_corrected(**stated) -> CorrectedTiming:
    return A_CORRECTED._replace(**stated)


def record(library, actor, run, timing, *, key=None, **stated) -> PlayerSession:
    dispatch(
        CreateSession(playthrough_id=run.pk, timing=timing, **stated),
        actor=actor,
        library=library,
        idempotency_key=key or str(uuid.uuid7()),
    )
    return PlayerSession.objects.get()


def refused(library, actor, run, timing, **stated) -> CommandRejected:
    with pytest.raises(CommandRejected) as refusal:
        dispatch(
            CreateSession(playthrough_id=run.pk, timing=timing, **stated),
            actor=actor,
            library=library,
            idempotency_key=str(uuid.uuid7()),
        )
    assert refusal.value.sentence
    return refusal.value


def test_a_timed_session_is_recorded(owned_user, owned_library, run):
    session = record(owned_library, owned_user, run, a_timed())

    assert session.timing_mode == PlayerSessionTimingMode.TIMED
    assert session.started_at == START
    assert session.effective_day == date(2026, 1, 2)
    assert session.effective_duration == timedelta(0)
    assert (
        LibraryEvent.objects.filter(event_type="library.playersession.created").count()
        == 1
    )


def test_a_finished_timed_session_is_recorded(owned_user, owned_library, run):
    session = record(
        owned_library,
        owned_user,
        run,
        a_timed(ended_at=START + timedelta(hours=2), ended_at_zone="Asia/Tokyo"),
    )

    assert session.effective_duration == timedelta(hours=2)
    assert session.ended_at_zone == "Asia/Tokyo"


def test_a_duration_only_session_is_recorded(owned_user, owned_library, run):
    session = record(owned_library, owned_user, run, a_duration_only())

    assert session.timing_mode == PlayerSessionTimingMode.DURATION_ONLY
    assert session.effective_day == date(2026, 3, 5)
    assert session.effective_duration == timedelta(minutes=90)
    assert session.day_zone is None


def test_a_corrected_session_states_the_duration_that_replaces_elapsed_time(
    owned_user, owned_library, run
):
    session = record(owned_library, owned_user, run, a_corrected())

    assert session.timing_mode == PlayerSessionTimingMode.CORRECTED
    assert session.effective_duration == timedelta(minutes=30)


def test_a_session_names_a_device(owned_user, owned_library, run):
    device = Device.objects.create(library=owned_library, name="Steam Deck")

    session = record(owned_library, owned_user, run, a_timed(), device_id=device.pk)

    assert session.device == device


def test_the_note_is_stripped(owned_user, owned_library, run):
    session = record(owned_library, owned_user, run, a_timed(), note="  played  ")

    assert session.note == "played"


def test_it_refuses_a_run_another_library_holds(
    owned_user, owned_library, second_library
):
    game = Game.objects.create(library=second_library, name="Elsewhere")
    tracked = PlayerGame.objects.create(
        id=uuid.uuid7(),
        library=second_library,
        game=game,
        tracked_at=timezone.now(),
    )
    other_run = Playthrough.objects.create(
        id=uuid.uuid7(),
        library=second_library,
        player_game=tracked,
        kind="ordinary",
        created_at=timezone.now(),
    )

    refused(owned_library, owned_user, other_run, a_timed())


def test_it_refuses_a_removed_run(owned_user, owned_library, run):
    Playthrough.objects.filter(pk=run.pk).update(removed_at=timezone.now())

    refused(owned_library, owned_user, run, a_timed())


def test_it_refuses_a_run_under_a_removed_game(owned_user, owned_library, run):
    PlayerGame.objects.filter(pk=run.player_game_id).update(removed_at=timezone.now())

    refused(owned_library, owned_user, run, a_timed())


def test_it_refuses_a_device_another_library_holds(
    owned_user, owned_library, run, second_library
):
    device = Device.objects.create(library=second_library, name="Elsewhere")

    refused(owned_library, owned_user, run, a_timed(), device_id=device.pk)


def test_it_refuses_a_removed_device(owned_user, owned_library, run):
    device = Device.objects.create(library=owned_library, name="Steam Deck")
    Device.objects.filter(pk=device.pk).update(removed_at=timezone.now())

    refused(owned_library, owned_user, run, a_timed(), device_id=device.pk)


def test_it_refuses_an_end_before_its_start(owned_user, owned_library, run):
    refused(
        owned_library, owned_user, run, a_timed(ended_at=START - timedelta(hours=1))
    )


def test_it_refuses_a_corrected_end_before_its_start(owned_user, owned_library, run):
    refused(
        owned_library,
        owned_user,
        run,
        a_corrected(ended_at=START - timedelta(hours=1)),
    )


def test_it_refuses_a_negative_duration(owned_user, owned_library, run):
    refused(
        owned_library, owned_user, run, a_duration_only(duration=-timedelta(minutes=1))
    )


def test_it_refuses_a_duration_finer_than_a_second(owned_user, owned_library, run):
    refused(
        owned_library,
        owned_user,
        run,
        a_duration_only(duration=timedelta(seconds=90, microseconds=1)),
    )


def test_it_refuses_a_duration_only_statement_of_nothing(
    owned_user, owned_library, run
):
    refused(owned_library, owned_user, run, a_duration_only(duration=timedelta(0)))


def test_it_refuses_a_negative_override(owned_user, owned_library, run):
    """The same rule on the other mode that states a duration.

    Without it the row reaches playersession_duration_not_negative
    as an IntegrityError, which answers() maps nowhere -- a 500
    raised after the stream head is locked.
    """
    refused(owned_library, owned_user, run, a_corrected(duration=-timedelta(minutes=1)))


def test_it_refuses_an_override_finer_than_a_second(owned_user, owned_library, run):
    """Truncating it would make an honest retry fingerprint anew."""
    refused(
        owned_library,
        owned_user,
        run,
        a_corrected(duration=timedelta(seconds=90, microseconds=1)),
    )


def test_it_refuses_an_end_zone_without_an_end(owned_user, owned_library, run):
    refused(owned_library, owned_user, run, a_timed(ended_at_zone="Asia/Tokyo"))


def test_it_refuses_a_naive_instant(owned_user, owned_library, run):
    #: noqa DTZ001: a naive datetime is exactly what is on trial.
    naive = datetime(2026, 1, 1, 12)  # noqa: DTZ001

    refused(owned_library, owned_user, run, a_timed(started_at=naive))


@pytest.mark.parametrize("field", ["day_zone", "started_at_zone"])
def test_it_refuses_a_zone_neither_tzdata_knows(owned_user, owned_library, run, field):
    refused(owned_library, owned_user, run, a_timed(**{field: "Not/AZone"}))


def test_it_refuses_a_note_jsonb_cannot_store(owned_user, owned_library, run):
    """A NUL byte survives strip() and dies inside the append.

    JSON carries it, JSONB refuses it, and the DataError that
    follows is raised after the stream head is locked and mapped
    to no answer at all.
    """
    refused(owned_library, owned_user, run, a_timed(), note="hi\x00there")


def test_it_refuses_a_session_with_no_day_zone(owned_user, owned_library, run):
    """The one zone that must be there, checked where it is stated."""
    refused(owned_library, owned_user, run, a_timed(day_zone=None))


def test_it_refuses_a_blank_day_zone(owned_user, owned_library, run):
    refusal = refused(owned_library, owned_user, run, a_timed(day_zone=" "))

    #: A blank is a zone nobody stated, not a zone we do not know.
    assert refusal.sentence == "Say which time zone this session's day is read in."


def test_it_refuses_a_zone_only_python_knows(
    owned_user, owned_library, run, monkeypatch
):
    """Both tzdata sets are read, not just the interpreter's.

    A name PostgreSQL lacks would pass the command and raise a
    DataError while `effective_day` is generated -- inside the
    append, and again mid-rebuild. The database's set is stubbed
    rather than found, because the two agree on this machine.
    """
    from games.commands import playersession as commands

    known = commands._database_zones()

    @lru_cache(maxsize=1)
    def without_prague() -> frozenset[str]:
        return known - {"Europe/Prague"}

    #: Cached like the real one, because a miss clears and re-reads.
    monkeypatch.setattr(commands, "_database_zones", without_prague)

    refused(owned_library, owned_user, run, a_timed(day_zone="Europe/Prague"))


def test_it_refuses_a_zone_only_the_database_knows(
    owned_user, owned_library, run, monkeypatch
):
    """And the interpreter's half is read too."""
    from games.commands import playersession as commands

    monkeypatch.setattr(commands, "zone_or_none", lambda name: None)

    refused(owned_library, owned_user, run, a_timed(day_zone="Europe/Prague"))


def test_a_retry_of_one_statement_appends_nothing_more(owned_user, owned_library, run):
    command = CreateSession(playthrough_id=run.pk, timing=a_timed())
    dispatch(command, actor=owned_user, library=owned_library, idempotency_key="one")

    second = dispatch(
        command, actor=owned_user, library=owned_library, idempotency_key="one"
    )

    assert second.outcome is CommandOutcome.REPLAYED
    assert PlayerSession.objects.count() == 1


def test_a_restated_duration_fingerprints_alike(owned_user, owned_library, run):
    dispatch(
        CreateSession(
            playthrough_id=run.pk, timing=a_duration_only(duration=timedelta(hours=1))
        ),
        actor=owned_user,
        library=owned_library,
        idempotency_key="one",
    )

    second = dispatch(
        CreateSession(
            playthrough_id=run.pk,
            timing=a_duration_only(duration=timedelta(minutes=60)),
        ),
        actor=owned_user,
        library=owned_library,
        idempotency_key="one",
    )

    assert second.outcome is CommandOutcome.REPLAYED


def test_it_never_answers_unchanged(owned_user, owned_library, run):
    for key in ("one", "two"):
        result = dispatch(
            CreateSession(playthrough_id=run.pk, timing=a_timed()),
            actor=owned_user,
            library=owned_library,
            idempotency_key=key,
        )
        assert result.outcome is CommandOutcome.APPENDED

    assert PlayerSession.objects.count() == 2


def test_a_refusal_the_command_forgot_reaches_a_person_as_a_sentence(
    owned_user, owned_library, run, monkeypatch, capture_games_logger
):
    """The backstop, exercised through the real stack.

    Every CHECK here is stricter than nothing and looser than the
    command, so reaching one means a guard is missing. Removing the
    duration guard is how that is staged: the database refuses the row
    inside the append, and `answered` turns the IntegrityError into a
    sentence instead of letting it rise as a 500.
    """
    monkeypatch.setattr(playersession_commands, "_check_duration", lambda _: None)

    with (
        capture_games_logger() as caplog,
        pytest.raises(CommandFailed) as failure,
        answered("session"),
    ):
        dispatch(
            CreateSession(
                playthrough_id=run.pk, timing=a_duration_only(duration=-timedelta(1))
            ),
            actor=owned_user,
            library=owned_library,
            idempotency_key=str(uuid.uuid7()),
        )

    assert failure.value.status_code == 500
    assert "playersession_duration_not_negative" not in failure.value.message
    #: Nothing was recorded: the append rolled back with it.
    assert not PlayerSession.objects.exists()
    assert not LibraryEvent.objects.filter(
        event_type="library.playersession.created"
    ).exists()
    assert "playersession_duration_not_negative" in caplog.text


# --- Ending a running session ------------------------------------------------

AN_END = START + timedelta(hours=2)


def ends(library, actor, session, *, ended_at, ended_at_zone=None, key=None):
    result = dispatch(
        EndSession(
            session_id=session.pk, ended_at=ended_at, ended_at_zone=ended_at_zone
        ),
        actor=actor,
        library=library,
        idempotency_key=key or str(uuid.uuid7()),
    )
    session.refresh_from_db()
    return result


def refused_end(
    library, actor, session_id, *, saying, ended_at=AN_END, ended_at_zone=None
) -> CommandRejected:
    """Refuse an end, and pin which refusal the person met.

    The sentence, not merely its presence: several of these rules
    refuse the same statement, so a test that asks only whether one
    fired stays green when the branch it names is taken away.
    """
    with pytest.raises(CommandRejected) as refusal:
        dispatch(
            EndSession(
                session_id=session_id, ended_at=ended_at, ended_at_zone=ended_at_zone
            ),
            actor=actor,
            library=library,
            idempotency_key=str(uuid.uuid7()),
        )
    assert refusal.value.sentence == saying
    return refusal.value


def test_it_ends_a_running_session(owned_user, owned_library, run):
    session = record(owned_library, owned_user, run, a_timed())

    result = ends(
        owned_library, owned_user, session, ended_at=AN_END, ended_at_zone="Asia/Tokyo"
    )

    assert result.outcome is CommandOutcome.APPENDED
    assert (session.ended_at, session.ended_at_zone) == (AN_END, "Asia/Tokyo")
    assert session.effective_duration == timedelta(hours=2)
    assert (
        LibraryEvent.objects.filter(event_type="library.playersession.ended").count()
        == 1
    )


def test_an_end_equal_to_the_start_is_recorded(owned_user, owned_library, run):
    """Started by mistake and ended at once; removal is the other remedy."""
    session = record(owned_library, owned_user, run, a_timed())

    ends(owned_library, owned_user, session, ended_at=START)

    assert session.ended_at == START
    assert session.effective_duration == timedelta(0)


def test_a_blank_zone_is_recorded_as_no_zone(owned_user, owned_library, run):
    session = record(owned_library, owned_user, run, a_timed())

    ends(owned_library, owned_user, session, ended_at=AN_END, ended_at_zone="   ")

    assert session.ended_at_zone is None


def test_an_empty_zone_normalizes_to_no_zone():
    """One statement, one digest, whichever way the caller spelled it."""
    blank = EndSession(session_id=uuid.uuid7(), ended_at=AN_END, ended_at_zone="")

    assert blank.ended_at_zone is None


def test_a_naive_end_is_refused_at_construction():
    #: noqa DTZ001: a naive datetime is exactly what is on trial.
    naive = datetime(2026, 1, 2, 1, 30)  # noqa: DTZ001

    with pytest.raises(CommandRejected) as refusal:
        EndSession(session_id=uuid.uuid7(), ended_at=naive, ended_at_zone=None)

    assert refusal.value.sentence


def test_restating_the_same_end_changes_nothing(owned_user, owned_library, run):
    session = record(owned_library, owned_user, run, a_timed())
    ends(
        owned_library, owned_user, session, ended_at=AN_END, ended_at_zone="Asia/Tokyo"
    )

    result = ends(
        owned_library, owned_user, session, ended_at=AN_END, ended_at_zone="Asia/Tokyo"
    )

    assert result.outcome is CommandOutcome.UNCHANGED
    assert (
        LibraryEvent.objects.filter(event_type="library.playersession.ended").count()
        == 1
    )


def test_the_same_instant_in_another_zone_is_refused(owned_user, owned_library, run):
    session = record(owned_library, owned_user, run, a_timed())
    ends(
        owned_library, owned_user, session, ended_at=AN_END, ended_at_zone="Asia/Tokyo"
    )

    refused_end(
        owned_library,
        owned_user,
        session.pk,
        ended_at=AN_END,
        ended_at_zone="Europe/Prague",
        saying=(
            "This session already has an end. Correct the one it has "
            "instead of stating another."
        ),
    )


def test_a_second_end_is_refused(owned_user, owned_library, run):
    session = record(owned_library, owned_user, run, a_timed())
    ends(owned_library, owned_user, session, ended_at=AN_END)

    refused_end(
        owned_library,
        owned_user,
        session.pk,
        ended_at=AN_END + timedelta(hours=1),
        saying=(
            "This session already has an end. Correct the one it has "
            "instead of stating another."
        ),
    )


def test_an_end_before_the_start_is_refused(owned_user, owned_library, run):
    session = record(owned_library, owned_user, run, a_timed())

    refused_end(
        owned_library,
        owned_user,
        session.pk,
        ended_at=START - timedelta(seconds=1),
        saying="This session would end before it started. Check the time.",
    )


def test_a_duration_only_session_has_no_end_to_state(owned_user, owned_library, run):
    session = record(owned_library, owned_user, run, a_duration_only())

    refused_end(
        owned_library,
        owned_user,
        session.pk,
        ended_at=AN_END,
        saying=(
            "This session records how long it lasted on a day, so it has "
            "no end to state."
        ),
    )


def test_a_corrected_session_already_has_an_end(owned_user, owned_library, run):
    session = record(owned_library, owned_user, run, a_corrected())

    refused_end(
        owned_library,
        owned_user,
        session.pk,
        ended_at=AN_END,
        saying=(
            "This session's time was already corrected, so it already has "
            "an end. Correct it again to change it."
        ),
    )


def test_a_zone_no_tzdata_knows_is_refused(owned_user, owned_library, run):
    session = record(owned_library, owned_user, run, a_timed())

    refused_end(
        owned_library,
        owned_user,
        session.pk,
        ended_at=AN_END,
        ended_at_zone="Mars/Olympus_Mons",
        saying="Mars/Olympus_Mons is not a time zone we know.",
    )


def test_an_unknown_session_is_refused(owned_user, owned_library, run):
    refused_end(
        owned_library,
        owned_user,
        uuid.uuid7(),
        ended_at=AN_END,
        saying="That session is not available.",
    )


def test_a_removed_session_is_refused(owned_user, owned_library, run):
    """Arranged with an UPDATE: nothing states a session's mark yet."""
    session = record(owned_library, owned_user, run, a_timed())
    PlayerSession.objects.filter(pk=session.pk).update(removed_at=timezone.now())

    refused_end(
        owned_library,
        owned_user,
        session.pk,
        ended_at=AN_END,
        saying=(
            "That session was removed from your library. Restore it "
            "before recording this."
        ),
    )


def test_ending_under_a_removed_run_is_refused(owned_user, owned_library, run):
    session = record(owned_library, owned_user, run, a_timed())
    Playthrough.objects.filter(pk=run.pk).update(removed_at=timezone.now())

    refused_end(
        owned_library,
        owned_user,
        session.pk,
        ended_at=AN_END,
        saying=(
            "That playthrough was removed from your library. Restore it "
            "before recording this."
        ),
    )


def test_ending_under_a_removed_game_is_refused(owned_user, owned_library, run):
    session = record(owned_library, owned_user, run, a_timed())
    PlayerGame.objects.filter(pk=run.player_game_id).update(removed_at=timezone.now())

    refused_end(
        owned_library,
        owned_user,
        session.pk,
        ended_at=AN_END,
        saying=(
            "That game was removed from your library. Restore it before recording this."
        ),
    )


def test_a_session_another_library_holds_is_refused(
    owned_user, owned_library, second_library
):
    game = Game.objects.create(library=second_library, name="Elsewhere")
    tracked = PlayerGame.objects.create(
        id=uuid.uuid7(),
        library=second_library,
        game=game,
        tracked_at=timezone.now(),
    )
    other_run = Playthrough.objects.create(
        id=uuid.uuid7(),
        library=second_library,
        player_game=tracked,
        kind="ordinary",
        created_at=timezone.now(),
    )
    elsewhere = PlayerSession.objects.create(
        id=uuid.uuid7(),
        library=second_library,
        playthrough=other_run,
        device=None,
        timing_mode=PlayerSessionTimingMode.TIMED,
        started_at=START,
        started_at_zone=None,
        ended_at=None,
        ended_at_zone=None,
        stated_day=None,
        stated_duration=None,
        day_zone="Europe/Prague",
        note="",
        emulated=False,
        created_at=timezone.now(),
    )

    refused_end(
        owned_library,
        owned_user,
        elsewhere.pk,
        ended_at=AN_END,
        saying=("That session is not available."),
    )


def test_a_day_zone_this_installation_cannot_read_is_refused(
    owned_user, owned_library, run, monkeypatch
):
    """A zone the row states and Python's tzdata has since lost.

    Arranged by taking the name away from `zone_or_none` rather than
    by writing a bad one: `effective_day` is generated before any
    constraint runs, so PostgreSQL refuses to store a zone it cannot
    read at all. The reachable state is the split one the two tzdata
    sets make possible -- the database still knows the name, this
    process no longer does. Unresolved it reaches the builder as a
    `ZoneInfoNotFoundError`, a `KeyError` the boundary does not
    answer, so nobody would be told anything.
    """
    session = record(owned_library, owned_user, run, a_timed())
    monkeypatch.setattr("games.commands.playersession.zone_or_none", lambda name: None)

    refused_end(
        owned_library,
        owned_user,
        session.pk,
        ended_at=AN_END,
        saying="We cannot read the time zone this session's day is counted in.",
    )


def test_a_timed_row_with_no_start_is_refused():
    """The state `playersession_timed_columns` forbids.

    Unreachable through the database, so it is stated against an
    unsaved row: the branch exists for a constraint somebody relaxes.
    """
    from games.commands.playersession import _timed_start

    broken = PlayerSession(
        timing_mode=PlayerSessionTimingMode.TIMED, started_at=None, day_zone=None
    )

    with pytest.raises(CommandRejected) as refusal:
        _timed_start(broken)

    assert refusal.value.sentence == "We cannot read that session's start time."


def test_a_padded_zone_states_the_name_inside_it(owned_user, owned_library, run):
    """One rule for a zone, whichever command reads it."""
    session = record(
        owned_library, owned_user, run, a_timed(started_at_zone=" Asia/Tokyo ")
    )

    assert session.started_at_zone == "Asia/Tokyo"


def test_a_dispatched_end_records_the_day_its_own_zone_reads(
    owned_user, owned_library, run
):
    """The command hands the row's day zone to the builder.

    The row keeps 2026-01-02; the event that ends it a day later
    states 2026-01-03, and nothing else in the suite joins those two
    halves.
    """
    session = record(owned_library, owned_user, run, a_timed())

    ends(owned_library, owned_user, session, ended_at=START + timedelta(days=1))

    ended = LibraryEvent.objects.get(event_type="library.playersession.ended")
    assert ended.effective_time.canonical == "2026-01-03"
    assert session.effective_day == date(2026, 1, 2)
