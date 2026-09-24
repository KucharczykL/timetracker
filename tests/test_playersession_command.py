"""Recording one session against a stated run."""

import itertools
import uuid
from datetime import UTC, date, datetime, timedelta
from datetime import timezone as dt_timezone
from functools import lru_cache

import pytest
from devices import create_device, remove_device
from django.utils import timezone

from games.commands import playersession as playersession_commands
from games.commands.playergame import TrackGame
from games.commands.playersession import (
    INTO_THE_BUCKET,
    CorrectedTiming,
    CorrectSessionTiming,
    CreateSession,
    DescribeSession,
    DurationOnlyTiming,
    EndSession,
    MoveSessionToPlaythrough,
    RemoveSession,
    RestoreSession,
    SessionNotHeld,
    StatedDevice,
    TimedTiming,
)
from games.commands.playthrough import (
    CreatePlaythrough,
    PlaythroughNotHeld,
    RemovePlaythrough,
    RestorePlaythrough,
)
from games.events.dispatch import (
    CommandOutcome,
    CommandRejected,
    RowNotHeld,
    RowUnreadable,
    dispatch,
)
from games.events.idempotency import IdempotencyKeyMismatch
from games.models import (
    Device,
    Game,
    LibraryEvent,
    PlayerGame,
    PlayerSession,
    PlayerSessionTimingMode,
    Playthrough,
    PlaythroughKind,
)
from games.writes.answers import CommandFailed, answered

pytestmark = [pytest.mark.untracked_games, pytest.mark.django_db(transaction=True)]

START = datetime(2026, 1, 1, 23, 30, tzinfo=UTC)


@pytest.fixture(autouse=True)
def prague_calendar(owned_user, set_user_setting):
    """Every statement below counts days in Prague, as the library does."""
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


def not_held(library, actor, run, timing, **stated) -> RowNotHeld:
    """A row this library does not hold; the boundary owns the answer."""
    with pytest.raises(RowNotHeld) as absent:
        dispatch(
            CreateSession(playthrough_id=run.pk, timing=timing, **stated),
            actor=actor,
            library=library,
            idempotency_key=str(uuid.uuid7()),
        )
    assert not hasattr(absent.value, "sentence")
    return absent.value


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
    device = create_device(library=owned_library, name="Steam Deck")

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

    not_held(owned_library, owned_user, other_run, a_timed())


def test_it_refuses_a_removed_run(owned_user, owned_library, run):
    Playthrough.objects.filter(pk=run.pk).update(removed_at=timezone.now())

    refused(owned_library, owned_user, run, a_timed())


def test_it_refuses_a_run_under_a_removed_game(owned_user, owned_library, run):
    PlayerGame.objects.filter(pk=run.player_game_id).update(removed_at=timezone.now())

    refused(owned_library, owned_user, run, a_timed())


def test_it_refuses_a_device_another_library_holds(
    owned_user, owned_library, run, second_library
):
    device = create_device(library=second_library, name="Elsewhere")

    not_held(owned_library, owned_user, run, a_timed(), device_id=device.pk)


def test_it_refuses_a_removed_device(owned_user, owned_library, run):
    device = create_device(library=owned_library, name="Steam Deck")
    remove_device(device)

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


OFF_CALENDAR = "This library counts days in Europe/Prague."


def test_it_refuses_a_day_zone_the_calendar_does_not_state(
    owned_user, owned_library, run
):
    refusal = refused(owned_library, owned_user, run, a_timed(day_zone="Asia/Tokyo"))

    assert refusal.sentence == OFF_CALENDAR
    assert not PlayerSession.objects.exists()


def test_a_correction_off_the_calendar_is_refused(owned_user, owned_library, run):
    session = record(owned_library, owned_user, run, a_timed())

    refused_correction(
        owned_library,
        owned_user,
        session.pk,
        a_timed(day_zone="Asia/Tokyo"),
        saying=OFF_CALENDAR,
    )


def test_a_corrected_statement_off_the_calendar_is_refused(
    owned_user, owned_library, run
):
    refusal = refused(
        owned_library, owned_user, run, a_corrected(day_zone="Asia/Tokyo")
    )

    assert refusal.sentence == OFF_CALENDAR


def test_it_refuses_a_session_with_no_day_zone(owned_user, owned_library, run):
    """The one zone that must be there, checked where it is stated."""
    refused(owned_library, owned_user, run, a_timed(day_zone=None))


def test_it_refuses_a_blank_day_zone(owned_user, owned_library, run):
    refusal = refused(owned_library, owned_user, run, a_timed(day_zone=" "))

    #: A blank is unstated, not unknown.
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


def states_the_sentence(refusal: Exception, saying: str | None) -> None:
    """A rejection states one; a row the library does not hold states none."""
    if isinstance(refusal, CommandRejected):
        assert refusal.sentence == saying
    else:
        assert saying is None


def refused_end(
    library,
    actor,
    session_id,
    *,
    saying: str | None,
    ended_at=AN_END,
    ended_at_zone=None,
    raising: type[Exception] = CommandRejected,
) -> Exception:
    """Refuse an end; pin sentence or type."""
    with pytest.raises(raising) as refusal:
        dispatch(
            EndSession(
                session_id=session_id, ended_at=ended_at, ended_at_zone=ended_at_zone
            ),
            actor=actor,
            library=library,
            idempotency_key=str(uuid.uuid7()),
        )
    states_the_sentence(refusal.value, saying)
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
        saying=None,
        raising=SessionNotHeld,
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
        saying=None,
        raising=SessionNotHeld,
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

    refusal = refused_end(
        owned_library,
        owned_user,
        session.pk,
        ended_at=AN_END,
        saying=None,
        raising=RowUnreadable,
    )

    assert "tzdata" in str(refusal)
    assert str(session.pk) in str(refusal)


def test_a_timed_row_with_no_start_is_refused():
    """The state `playersession_timed_columns` forbids.

    Unreachable through the database, so it is stated against an
    unsaved row: the branch exists for a constraint somebody relaxes.
    """
    from games.commands.playersession import _timed_start

    broken = PlayerSession(
        timing_mode=PlayerSessionTimingMode.TIMED, started_at=None, day_zone=None
    )

    with pytest.raises(RowUnreadable) as refusal:
        _timed_start(broken)

    assert "timed-columns constraint" in str(refusal.value)


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


# --- Correcting a session's timing -------------------------------------------

TIMING_STATES = {
    "timed-running": a_timed(),
    "timed-finished": a_timed(ended_at=AN_END, ended_at_zone="Asia/Tokyo"),
    "duration-only": a_duration_only(),
    "corrected": a_corrected(),
}

TRANSITIONS = list(itertools.permutations(TIMING_STATES, 2))


def corrects(library, actor, session_id, timing, *, key=None):
    return dispatch(
        CorrectSessionTiming(session_id=session_id, timing=timing),
        actor=actor,
        library=library,
        idempotency_key=key or str(uuid.uuid7()),
    )


def refused_correction(
    library,
    actor,
    session_id,
    timing,
    *,
    saying,
    raising: type[Exception] = CommandRejected,
):
    with pytest.raises(raising) as refusal:
        corrects(library, actor, session_id, timing)
    states_the_sentence(refusal.value, saying)
    return refusal.value


def a_session_another_library_holds(library) -> PlayerSession:
    """Rows, not events: another library's stream."""
    game = Game.objects.create(library=library, name="Elsewhere")
    tracked = PlayerGame.objects.create(
        id=uuid.uuid7(), library=library, game=game, tracked_at=timezone.now()
    )
    other_run = Playthrough.objects.create(
        id=uuid.uuid7(),
        library=library,
        player_game=tracked,
        kind="ordinary",
        created_at=timezone.now(),
    )
    return PlayerSession.objects.create(
        id=uuid.uuid7(),
        library=library,
        playthrough=other_run,
        timing_mode=PlayerSessionTimingMode.TIMED,
        started_at=START,
        day_zone="Europe/Prague",
        note="",
        emulated=False,
        created_at=timezone.now(),
    )


def correction_events():
    return LibraryEvent.objects.filter(
        event_type="library.playersession.timing_corrected"
    )


@pytest.mark.parametrize(
    ("before", "after"),
    TRANSITIONS,
    ids=[f"{before}->{after}" for before, after in TRANSITIONS],
)
def test_every_transition_is_recorded(owned_user, owned_library, run, before, after):
    session = record(owned_library, owned_user, run, TIMING_STATES[before])

    result = corrects(owned_library, owned_user, session.pk, TIMING_STATES[after])

    assert result.outcome is CommandOutcome.APPENDED
    session.refresh_from_db()
    assert correction_events().count() == 1
    assert (
        session.timing_mode
        == {
            "timed-running": PlayerSessionTimingMode.TIMED,
            "timed-finished": PlayerSessionTimingMode.TIMED,
            "duration-only": PlayerSessionTimingMode.DURATION_ONLY,
            "corrected": PlayerSessionTimingMode.CORRECTED,
        }[after]
    )


def test_a_corrected_session_may_run_again_and_then_end(owned_user, owned_library, run):
    """A mistaken end has a remedy."""
    session = record(owned_library, owned_user, run, a_corrected())

    corrects(owned_library, owned_user, session.pk, a_timed())
    ends(owned_library, owned_user, session, ended_at=AN_END)

    assert session.timing_mode == PlayerSessionTimingMode.TIMED
    assert session.ended_at == AN_END


@pytest.mark.parametrize("state", TIMING_STATES)
def test_restating_the_row_changes_nothing(owned_user, owned_library, run, state):
    session = record(owned_library, owned_user, run, TIMING_STATES[state])

    result = corrects(owned_library, owned_user, session.pk, TIMING_STATES[state])

    assert result.outcome is CommandOutcome.UNCHANGED
    assert not correction_events().exists()


@pytest.mark.parametrize(
    ("before", "after", "column", "value"),
    [
        (
            a_corrected(),
            a_corrected(duration=timedelta(minutes=45)),
            "stated_duration",
            timedelta(minutes=45),
        ),
        (
            a_duration_only(),
            a_duration_only(day=date(2026, 3, 6)),
            "stated_day",
            date(2026, 3, 6),
        ),
        (
            TIMING_STATES["timed-finished"],
            a_timed(ended_at=AN_END, ended_at_zone="Europe/Prague"),
            "ended_at_zone",
            "Europe/Prague",
        ),
    ],
    ids=["override", "written-day", "end-zone"],
)
def test_a_correction_within_one_mode_is_recorded(
    owned_user, owned_library, run, before, after, column, value
):
    session = record(owned_library, owned_user, run, before)

    result = corrects(owned_library, owned_user, session.pk, after)

    assert result.outcome is CommandOutcome.APPENDED
    session.refresh_from_db()
    assert getattr(session, column) == value


def test_a_padded_restatement_changes_nothing(owned_user, owned_library, run):
    session = record(
        owned_library, owned_user, run, a_timed(started_at_zone="Asia/Tokyo")
    )

    result = corrects(
        owned_library,
        owned_user,
        session.pk,
        a_timed(started_at_zone=" Asia/Tokyo ", day_zone=" Europe/Prague"),
    )

    assert result.outcome is CommandOutcome.UNCHANGED


def test_the_same_instants_in_another_zone_are_a_correction(
    owned_user, owned_library, run
):
    session = record(owned_library, owned_user, run, a_timed())

    result = corrects(
        owned_library, owned_user, session.pk, a_timed(started_at_zone="Asia/Tokyo")
    )

    assert result.outcome is CommandOutcome.APPENDED
    session.refresh_from_db()
    assert session.started_at_zone == "Asia/Tokyo"


def test_a_retry_of_one_correction_appends_nothing_more(owned_user, owned_library, run):
    session = record(owned_library, owned_user, run, a_timed())

    corrects(owned_library, owned_user, session.pk, a_corrected(), key="correct")
    result = corrects(
        owned_library, owned_user, session.pk, a_corrected(), key="correct"
    )

    assert result.outcome is CommandOutcome.REPLAYED
    assert correction_events().count() == 1


def test_a_correction_is_dated_by_the_day_it_now_states(owned_user, owned_library, run):
    session = record(owned_library, owned_user, run, a_timed())

    corrects(owned_library, owned_user, session.pk, a_duration_only())

    assert correction_events().get().effective_time.canonical == "2026-03-05"


@pytest.mark.parametrize(
    ("timing", "saying"),
    [
        (
            a_timed(ended_at=START - timedelta(hours=1)),
            "This session ended before it started. Check the times.",
        ),
        (
            a_duration_only(duration=-timedelta(minutes=1)),
            "A session cannot last a negative amount of time.",
        ),
        (
            a_corrected(duration=timedelta(seconds=1, microseconds=1)),
            "State this session's length in whole seconds.",
        ),
        (a_duration_only(duration=timedelta(0)), "Say how long this session lasted."),
        (
            a_timed(started_at_zone="Mars/Olympus_Mons"),
            "Mars/Olympus_Mons is not a time zone we know.",
        ),
        (
            a_timed(day_zone=""),
            "Say which time zone this session's day is read in.",
        ),
        (
            a_timed(ended_at_zone="Asia/Tokyo"),
            "This session has no end time, so it cannot have an end time zone.",
        ),
    ],
    ids=[
        "end-before-start",
        "negative",
        "finer-than-a-second",
        "zero",
        "unknown-zone",
        "blank-day-zone",
        "end-zone-without-end",
    ],
)
def test_a_correction_meets_every_rule_the_creation_does(
    owned_user, owned_library, run, timing, saying
):
    session = record(owned_library, owned_user, run, a_timed())

    refused_correction(owned_library, owned_user, session.pk, timing, saying=saying)


def test_an_invalid_restatement_is_refused_not_unchanged(
    owned_user, owned_library, run
):
    """Rules run before the comparison."""
    session = record(owned_library, owned_user, run, a_timed())
    PlayerSession.objects.filter(pk=session.pk).update(started_at_zone="Mars/Base")

    refused_correction(
        owned_library,
        owned_user,
        session.pk,
        a_timed(started_at_zone="Mars/Base"),
        saying="Mars/Base is not a time zone we know.",
    )


def test_a_naive_correction_is_refused_at_construction():
    naive = datetime(2026, 1, 1)  # noqa: DTZ001

    with pytest.raises(CommandRejected):
        CorrectSessionTiming(session_id=uuid.uuid7(), timing=a_timed(started_at=naive))


def test_a_timestamp_is_not_a_written_day():
    """`datetime` subclasses `date`, so mypy admits it."""
    with pytest.raises(TypeError):
        CorrectSessionTiming(
            session_id=uuid.uuid7(),
            timing=a_duration_only(day=datetime(2026, 3, 5, 10, tzinfo=UTC)),
        )


def test_an_unknown_session_has_no_timing_to_correct(owned_user, owned_library):
    refused_correction(
        owned_library,
        owned_user,
        uuid.uuid7(),
        a_timed(),
        saying=None,
        raising=SessionNotHeld,
    )


def test_another_librarys_session_has_no_timing_to_correct(
    owned_user, owned_library, second_library
):
    elsewhere = a_session_another_library_holds(second_library)

    refused_correction(
        owned_library,
        owned_user,
        elsewhere.pk,
        a_timed(),
        saying=None,
        raising=SessionNotHeld,
    )


def test_a_correction_under_a_removed_run_is_refused(owned_user, owned_library, run):
    session = record(owned_library, owned_user, run, a_timed())
    Playthrough.objects.filter(pk=run.pk).update(removed_at=timezone.now())

    refused_correction(
        owned_library,
        owned_user,
        session.pk,
        a_corrected(),
        saying=(
            "That playthrough was removed from your library. Restore it "
            "before recording this."
        ),
    )


def test_a_correction_under_a_removed_game_is_refused(owned_user, owned_library, run):
    session = record(owned_library, owned_user, run, a_timed())
    PlayerGame.objects.filter(pk=run.player_game_id).update(removed_at=timezone.now())

    refused_correction(
        owned_library,
        owned_user,
        session.pk,
        a_corrected(),
        saying=(
            "That game was removed from your library. Restore it before recording this."
        ),
    )


def test_resetting_a_running_session_restates_its_start(owned_user, owned_library, run):
    """What the reset screen sends."""
    session = record(owned_library, owned_user, run, a_timed())
    now = START + timedelta(hours=3)

    corrects(
        owned_library,
        owned_user,
        session.pk,
        TimedTiming(
            started_at=now, day_zone=session.day_zone, started_at_zone="Asia/Tokyo"
        ),
    )

    session.refresh_from_db()
    assert (session.started_at, session.started_at_zone, session.ended_at) == (
        now,
        "Asia/Tokyo",
        None,
    )


def test_resetting_a_finished_session_runs_it_again(owned_user, owned_library, run):
    """The reset statement holds no end."""
    session = record(owned_library, owned_user, run, a_timed(ended_at=AN_END))
    now = AN_END + timedelta(hours=1)

    corrects(
        owned_library,
        owned_user,
        session.pk,
        TimedTiming(started_at=now, day_zone="Europe/Prague"),
    )

    session.refresh_from_db()
    assert (session.started_at, session.ended_at) == (now, None)


# --- Describing a session ----------------------------------------------------


def describes(library, actor, session_id, *, key=None, **stated):
    return dispatch(
        DescribeSession(session_id=session_id, **stated),
        actor=actor,
        library=library,
        idempotency_key=key or str(uuid.uuid7()),
    )


def refused_description(
    library,
    actor,
    session_id,
    *,
    saying,
    raising: type[Exception] = CommandRejected,
    **stated,
):
    with pytest.raises(raising) as refusal:
        describes(library, actor, session_id, **stated)
    states_the_sentence(refusal.value, saying)
    return refusal.value


def description_events() -> list[str]:
    return list(
        LibraryEvent.objects.filter(
            event_type__in=[
                "library.playersession.note_changed",
                "library.playersession.device_changed",
                "library.playersession.emulated_changed",
            ]
        )
        .order_by("sequence")
        .values_list("event_type", flat=True)
    )


@pytest.fixture
def steam_deck(owned_library) -> Device:
    return create_device(library=owned_library, name="Steam Deck")


def test_a_note_alone_is_described(owned_user, owned_library, run):
    session = record(owned_library, owned_user, run, a_timed(), note="before")

    describes(owned_library, owned_user, session.pk, note="after")

    session.refresh_from_db()
    assert session.note == "after"
    assert description_events() == ["library.playersession.note_changed"]


def test_a_device_alone_is_described(owned_user, owned_library, run, steam_deck):
    session = record(owned_library, owned_user, run, a_timed())

    describes(owned_library, owned_user, session.pk, device=StatedDevice(steam_deck.pk))

    session.refresh_from_db()
    assert session.device == steam_deck
    assert description_events() == ["library.playersession.device_changed"]


def test_the_emulated_flag_alone_is_described(owned_user, owned_library, run):
    session = record(owned_library, owned_user, run, a_timed())

    describes(owned_library, owned_user, session.pk, emulated=True)

    session.refresh_from_db()
    assert session.emulated is True
    assert description_events() == ["library.playersession.emulated_changed"]


def test_the_emulated_flag_is_cleared(owned_user, owned_library, run):
    session = record(owned_library, owned_user, run, a_timed(), emulated=True)

    result = describes(owned_library, owned_user, session.pk, emulated=False)

    assert result.outcome is CommandOutcome.APPENDED
    session.refresh_from_db()
    assert session.emulated is False


def test_three_facts_are_three_events(owned_user, owned_library, run, steam_deck):
    session = record(owned_library, owned_user, run, a_timed())

    result = describes(
        owned_library,
        owned_user,
        session.pk,
        note="played",
        device=StatedDevice(steam_deck.pk),
        emulated=True,
    )

    assert result.outcome is CommandOutcome.APPENDED
    assert description_events() == [
        "library.playersession.note_changed",
        "library.playersession.device_changed",
        "library.playersession.emulated_changed",
    ]


def test_only_the_facts_that_differ_are_recorded(owned_user, owned_library, run):
    session = record(owned_library, owned_user, run, a_timed(), note="played")

    describes(owned_library, owned_user, session.pk, note="played", emulated=True)

    assert description_events() == ["library.playersession.emulated_changed"]


def test_an_empty_note_clears_the_note(owned_user, owned_library, run):
    session = record(owned_library, owned_user, run, a_timed(), note="played")

    describes(owned_library, owned_user, session.pk, note="")

    session.refresh_from_db()
    assert session.note == ""


def test_a_padded_note_is_compared_as_the_note_inside_it(
    owned_user, owned_library, run
):
    session = record(owned_library, owned_user, run, a_timed(), note="played")

    result = describes(owned_library, owned_user, session.pk, note="  played ")

    assert result.outcome is CommandOutcome.UNCHANGED


def test_a_padded_note_fingerprints_as_the_note_inside_it(
    owned_user, owned_library, run
):
    session = record(owned_library, owned_user, run, a_timed())

    describes(owned_library, owned_user, session.pk, note=" played", key="describe")
    result = describes(
        owned_library, owned_user, session.pk, note="played", key="describe"
    )

    assert result.outcome is CommandOutcome.REPLAYED


def test_stating_no_device_clears_the_device(
    owned_user, owned_library, run, steam_deck
):
    session = record(owned_library, owned_user, run, a_timed(), device_id=steam_deck.pk)

    describes(owned_library, owned_user, session.pk, device=StatedDevice(None))

    session.refresh_from_db()
    assert session.device is None


def test_an_unstated_device_is_left_alone(owned_user, owned_library, run, steam_deck):
    session = record(owned_library, owned_user, run, a_timed(), device_id=steam_deck.pk)

    describes(owned_library, owned_user, session.pk, note="played")

    session.refresh_from_db()
    assert session.device == steam_deck


def test_a_note_jsonb_cannot_store_is_refused(owned_user, owned_library, run):
    session = record(owned_library, owned_user, run, a_timed())

    refused_description(
        owned_library,
        owned_user,
        session.pk,
        note="hi\x00there",
        saying="That note contains a character we cannot store.",
    )


def test_a_note_holding_a_lone_surrogate_is_refused(owned_user, owned_library, run):
    """A JSON body can carry one; JSONB refuses it."""
    session = record(owned_library, owned_user, run, a_timed())

    refused_description(
        owned_library,
        owned_user,
        session.pk,
        note="a\ud800",
        saying="That note contains a character we cannot store.",
    )


def test_another_librarys_device_is_refused(
    owned_user, owned_library, run, second_library
):
    session = record(owned_library, owned_user, run, a_timed())
    elsewhere = create_device(library=second_library, name="Elsewhere")

    refused_description(
        owned_library,
        owned_user,
        session.pk,
        device=StatedDevice(elsewhere.pk),
        saying=None,
        raising=RowNotHeld,
    )


def test_a_removed_device_is_refused(owned_user, owned_library, run, steam_deck):
    session = record(owned_library, owned_user, run, a_timed())
    remove_device(steam_deck)

    refused_description(
        owned_library,
        owned_user,
        session.pk,
        device=StatedDevice(steam_deck.pk),
        saying=(
            "That device was removed from your library. Restore it before choosing it."
        ),
    )


def test_restating_a_removed_device_the_row_names_changes_nothing(
    owned_user, owned_library, run, steam_deck
):
    """Compared before resolved; removal is irrelevant."""
    session = record(owned_library, owned_user, run, a_timed(), device_id=steam_deck.pk)
    remove_device(steam_deck)

    result = describes(
        owned_library, owned_user, session.pk, device=StatedDevice(steam_deck.pk)
    )

    assert result.outcome is CommandOutcome.UNCHANGED


def test_a_description_of_nothing_is_refused():
    with pytest.raises(CommandRejected) as refusal:
        DescribeSession(session_id=uuid.uuid7())

    assert refusal.value.sentence == "Say what to change about this session."


def test_an_unknown_session_has_nothing_to_describe(owned_user, owned_library):
    refused_description(
        owned_library,
        owned_user,
        uuid.uuid7(),
        note="played",
        saying=None,
        raising=SessionNotHeld,
    )


def test_another_librarys_session_has_nothing_to_describe(
    owned_user, owned_library, second_library
):
    elsewhere = a_session_another_library_holds(second_library)

    refused_description(
        owned_library,
        owned_user,
        elsewhere.pk,
        note="played",
        saying=None,
        raising=SessionNotHeld,
    )


def test_a_description_under_a_removed_run_is_refused(owned_user, owned_library, run):
    session = record(owned_library, owned_user, run, a_timed())
    Playthrough.objects.filter(pk=run.pk).update(removed_at=timezone.now())

    refused_description(
        owned_library,
        owned_user,
        session.pk,
        note="played",
        saying=(
            "That playthrough was removed from your library. Restore it "
            "before recording this."
        ),
    )


def test_stating_no_device_is_a_different_statement(
    owned_user, owned_library, run, steam_deck
):
    """`StatedDevice(None)` is not an unstated fact."""
    session = record(
        owned_library,
        owned_user,
        run,
        a_timed(),
        note="played",
        device_id=steam_deck.pk,
    )

    describes(owned_library, owned_user, session.pk, note="other", key="one")
    with pytest.raises(IdempotencyKeyMismatch):
        describes(
            owned_library,
            owned_user,
            session.pk,
            note="other",
            device=StatedDevice(None),
            key="one",
        )


# --- Moving a session to another playthrough ---------------------------------


def moves(library, actor, session_id, playthrough_id, *, key=None):
    return dispatch(
        MoveSessionToPlaythrough(session_id=session_id, playthrough_id=playthrough_id),
        actor=actor,
        library=library,
        idempotency_key=key or str(uuid.uuid7()),
    )


def refused_move(
    library,
    actor,
    session_id,
    playthrough_id,
    *,
    saying,
    raising: type[Exception] = CommandRejected,
):
    with pytest.raises(raising) as refusal:
        moves(library, actor, session_id, playthrough_id)
    states_the_sentence(refusal.value, saying)
    return refusal.value


def move_events():
    return LibraryEvent.objects.filter(event_type="library.playersession.moved")


@pytest.fixture
def other_game_run(owned_user, owned_library) -> Playthrough:
    other_game = Game.objects.create(library=owned_library, name="Tunic")
    dispatch(
        TrackGame(game_id=other_game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="track-other",
    )
    return Playthrough.objects.get(player_game__game=other_game)


def test_a_session_moves_to_another_run_at_its_game(owned_user, owned_library, run):
    second_run = Playthrough.objects.create(
        id=uuid.uuid7(),
        library=owned_library,
        player_game=run.player_game,
        kind=PlaythroughKind.ORDINARY,
        created_at=timezone.now(),
    )
    session = record(owned_library, owned_user, run, a_timed())

    moves(owned_library, owned_user, session.pk, second_run.pk)

    session.refresh_from_db()
    assert session.playthrough == second_run


def test_a_session_logged_against_the_wrong_game_moves_to_the_right_one(
    owned_user, owned_library, run, other_game_run
):
    session = record(owned_library, owned_user, run, a_corrected(), note="played")
    kept = {
        name: getattr(session, name)
        for name in ("timing_mode", "started_at", "stated_duration", "note")
    }

    moves(owned_library, owned_user, session.pk, other_game_run.pk)

    session.refresh_from_db()
    assert session.playthrough.player_game.game.name == "Tunic"
    assert {name: getattr(session, name) for name in kept} == kept
    assert move_events().count() == 1


def test_a_session_may_move_to_imported_history(owned_user, owned_library, run):
    history = Playthrough.objects.create(
        id=uuid.uuid7(),
        library=owned_library,
        player_game=run.player_game,
        kind=PlaythroughKind.IMPORTED_HISTORY,
        created_at=timezone.now(),
    )
    session = record(owned_library, owned_user, run, a_timed())

    result = moves(owned_library, owned_user, session.pk, history.pk)

    assert result.outcome is CommandOutcome.APPENDED


def test_moving_to_the_same_run_changes_nothing(owned_user, owned_library, run):
    session = record(owned_library, owned_user, run, a_timed())

    result = moves(owned_library, owned_user, session.pk, run.pk)

    assert result.outcome is CommandOutcome.UNCHANGED
    assert not move_events().exists()


def test_a_run_another_library_holds_is_refused(
    owned_user, owned_library, run, second_library
):
    session = record(owned_library, owned_user, run, a_timed())
    elsewhere = a_session_another_library_holds(second_library)

    refused_move(
        owned_library,
        owned_user,
        session.pk,
        elsewhere.playthrough_id,
        saying=None,
        raising=PlaythroughNotHeld,
    )


def test_an_unknown_run_is_refused(owned_user, owned_library, run):
    session = record(owned_library, owned_user, run, a_timed())

    refused_move(
        owned_library,
        owned_user,
        session.pk,
        uuid.uuid7(),
        saying=None,
        raising=PlaythroughNotHeld,
    )


def test_a_removed_target_run_is_refused(
    owned_user, owned_library, run, other_game_run
):
    session = record(owned_library, owned_user, run, a_timed())
    Playthrough.objects.filter(pk=other_game_run.pk).update(removed_at=timezone.now())

    refused_move(
        owned_library,
        owned_user,
        session.pk,
        other_game_run.pk,
        saying=(
            "That playthrough was removed from your library. Restore it "
            "before recording this."
        ),
    )


def test_a_target_under_a_removed_game_is_refused(
    owned_user, owned_library, run, other_game_run
):
    session = record(owned_library, owned_user, run, a_timed())
    PlayerGame.objects.filter(pk=other_game_run.player_game_id).update(
        removed_at=timezone.now()
    )

    refused_move(
        owned_library,
        owned_user,
        session.pk,
        other_game_run.pk,
        saying=(
            "That game was removed from your library. Restore it before recording this."
        ),
    )


def test_a_session_under_a_removed_game_cannot_be_moved_out(
    owned_user, owned_library, run, other_game_run
):
    """No read finds such a session."""
    session = record(owned_library, owned_user, run, a_timed())
    PlayerGame.objects.filter(pk=run.player_game_id).update(removed_at=timezone.now())

    refused_move(
        owned_library,
        owned_user,
        session.pk,
        other_game_run.pk,
        saying=(
            "That game was removed from your library. Restore it before recording this."
        ),
    )


def test_an_unknown_session_cannot_be_moved(owned_user, owned_library, run):
    refused_move(
        owned_library,
        owned_user,
        uuid.uuid7(),
        run.pk,
        saying=None,
        raising=SessionNotHeld,
    )


# --- Removing and restoring a session ----------------------------------------


REMOVED_SESSION_SENTENCE = (
    "That session was removed from your library. Restore it before recording this."
)


def removes(library, actor, session_id, *, key=None):
    return dispatch(
        RemoveSession(session_id=session_id),
        actor=actor,
        library=library,
        idempotency_key=key or str(uuid.uuid7()),
    )


def restores(library, actor, session_id, *, key=None):
    return dispatch(
        RestoreSession(session_id=session_id),
        actor=actor,
        library=library,
        idempotency_key=key or str(uuid.uuid7()),
    )


def refused_lifecycle(
    command,
    library,
    actor,
    session_id,
    *,
    saying,
    raising: type[Exception] = CommandRejected,
):
    with pytest.raises(raising) as refusal:
        dispatch(
            command(session_id=session_id),
            actor=actor,
            library=library,
            idempotency_key=str(uuid.uuid7()),
        )
    states_the_sentence(refusal.value, saying)
    return refusal.value


def lifecycle_events(library) -> list[str]:
    return list(
        LibraryEvent.objects.filter(
            library=library,
            event_type__in=[
                "library.playersession.removed",
                "library.playersession.restored",
            ],
        )
        .order_by("sequence")
        .values_list("event_type", flat=True)
    )


def test_a_removal_leaves_the_reads(owned_user, owned_library, run):
    session = record(owned_library, owned_user, run, a_timed())

    result = removes(owned_library, owned_user, session.pk)

    assert result.outcome is CommandOutcome.APPENDED
    stamped = LibraryEvent.objects.get(
        event_type="library.playersession.removed"
    ).recorded_at
    session.refresh_from_db()
    assert session.removed_at == stamped
    assert not PlayerSession.objects.alive().exists()
    assert PlayerSession.objects.get() == session


def test_a_restore_states_the_way_back(owned_user, owned_library, run):
    session = record(owned_library, owned_user, run, a_timed())
    removes(owned_library, owned_user, session.pk)

    result = restores(owned_library, owned_user, session.pk)

    assert result.outcome is CommandOutcome.APPENDED
    session.refresh_from_db()
    assert session.removed_at is None
    assert PlayerSession.objects.alive().get() == session
    assert lifecycle_events(owned_library) == [
        "library.playersession.removed",
        "library.playersession.restored",
    ]


def test_removing_a_removed_session_changes_nothing(owned_user, owned_library, run):
    session = record(owned_library, owned_user, run, a_timed())
    removes(owned_library, owned_user, session.pk)

    result = removes(owned_library, owned_user, session.pk)

    assert result.outcome is CommandOutcome.UNCHANGED
    assert lifecycle_events(owned_library) == ["library.playersession.removed"]


def test_restoring_a_live_session_changes_nothing(owned_user, owned_library, run):
    session = record(owned_library, owned_user, run, a_timed())

    result = restores(owned_library, owned_user, session.pk)

    assert result.outcome is CommandOutcome.UNCHANGED
    assert lifecycle_events(owned_library) == []


def test_one_key_covers_a_repeated_removal(owned_user, owned_library, run):
    session = record(owned_library, owned_user, run, a_timed())

    removes(owned_library, owned_user, session.pk, key="remove")
    removes(owned_library, owned_user, session.pk, key="remove")

    assert lifecycle_events(owned_library) == ["library.playersession.removed"]


def test_one_key_covers_a_repeated_restore(owned_user, owned_library, run):
    session = record(owned_library, owned_user, run, a_timed())
    removes(owned_library, owned_user, session.pk)

    restores(owned_library, owned_user, session.pk, key="restore")
    restores(owned_library, owned_user, session.pk, key="restore")

    assert lifecycle_events(owned_library) == [
        "library.playersession.removed",
        "library.playersession.restored",
    ]


@pytest.mark.parametrize("command", [RemoveSession, RestoreSession])
def test_an_unknown_session_is_refused_alike(owned_user, owned_library, command):
    refused_lifecycle(
        command,
        owned_library,
        owned_user,
        uuid.uuid7(),
        saying=None,
        raising=SessionNotHeld,
    )


@pytest.mark.parametrize("command", [RemoveSession, RestoreSession])
def test_another_librarys_session_is_refused_alike(
    owned_user, owned_library, second_library, command
):
    elsewhere = a_session_another_library_holds(second_library)

    refused_lifecycle(
        command,
        owned_library,
        owned_user,
        elsewhere.pk,
        saying=None,
        raising=SessionNotHeld,
    )
    elsewhere.refresh_from_db()
    assert elsewhere.removed_at is None


def _arranged_for(command, library, actor, session) -> None:
    """A restore names a removed row."""
    if command is RestoreSession:
        removes(library, actor, session.pk)


@pytest.mark.parametrize("command", [RemoveSession, RestoreSession])
def test_a_lifecycle_act_under_a_removed_run_is_refused(
    owned_user, owned_library, run, command
):
    session = record(owned_library, owned_user, run, a_timed())
    _arranged_for(command, owned_library, owned_user, session)
    Playthrough.objects.filter(pk=run.pk).update(removed_at=timezone.now())

    refused_lifecycle(
        command,
        owned_library,
        owned_user,
        session.pk,
        saying=(
            "That playthrough was removed from your library. Restore it "
            "before changing its sessions."
        ),
    )


@pytest.mark.parametrize("command", [RemoveSession, RestoreSession])
@pytest.mark.parametrize("run_removed", [False, True], ids=["game-alone", "both"])
def test_a_lifecycle_act_under_a_removed_game_is_refused(
    owned_user, owned_library, run, command, run_removed
):
    """The game's mark answers first."""
    session = record(owned_library, owned_user, run, a_timed())
    _arranged_for(command, owned_library, owned_user, session)
    if run_removed:
        Playthrough.objects.filter(pk=run.pk).update(removed_at=timezone.now())
    PlayerGame.objects.filter(pk=run.player_game_id).update(removed_at=timezone.now())

    refused_lifecycle(
        command,
        owned_library,
        owned_user,
        session.pk,
        saying=(
            "That game was removed from your library. Restore it before "
            "changing its sessions."
        ),
    )


def test_a_repeated_removal_still_succeeds_once_the_run_is_gone(
    owned_user, owned_library, run
):
    """The no-op ahead of every refusal."""
    session = record(owned_library, owned_user, run, a_timed())
    removes(owned_library, owned_user, session.pk)
    Playthrough.objects.filter(pk=run.pk).update(removed_at=timezone.now())

    result = removes(owned_library, owned_user, session.pk)

    assert result.outcome is CommandOutcome.UNCHANGED


def test_a_restore_of_a_live_session_still_succeeds_once_the_game_is_gone(
    owned_user, owned_library, run
):
    session = record(owned_library, owned_user, run, a_timed())
    PlayerGame.objects.filter(pk=run.player_game_id).update(removed_at=timezone.now())

    result = restores(owned_library, owned_user, session.pk)

    assert result.outcome is CommandOutcome.UNCHANGED


@pytest.mark.parametrize(
    "statement",
    [
        lambda session, target: EndSession(
            session_id=session.pk, ended_at=AN_END, ended_at_zone=None
        ),
        lambda session, target: CorrectSessionTiming(
            session_id=session.pk, timing=a_duration_only()
        ),
        lambda session, target: DescribeSession(session_id=session.pk, note="late"),
        lambda session, target: MoveSessionToPlaythrough(
            session_id=session.pk, playthrough_id=target.pk
        ),
    ],
    ids=["end", "correct", "describe", "move"],
)
def test_a_removed_session_refuses_every_statement(
    owned_user, owned_library, run, other_game_run, statement
):
    session = record(owned_library, owned_user, run, a_timed())
    removes(owned_library, owned_user, session.pk)

    with pytest.raises(CommandRejected) as refusal:
        dispatch(
            statement(session, other_game_run),
            actor=owned_user,
            library=owned_library,
            idempotency_key=str(uuid.uuid7()),
        )

    assert refusal.value.sentence == REMOVED_SESSION_SENTENCE


def test_the_way_back_is_run_then_session(owned_user, owned_library, game, run):
    """Each refusal names a step, and each step works."""
    dispatch(
        CreatePlaythrough(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="second-run",
    )
    second = Playthrough.objects.exclude(pk=run.pk).get()
    session = record(owned_library, owned_user, second, a_timed())
    removes(owned_library, owned_user, session.pk)
    removed_run = dispatch(
        RemovePlaythrough(playthrough_id=second.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="remove-run",
    )
    assert removed_run.outcome is CommandOutcome.APPENDED
    refused_lifecycle(
        RestoreSession,
        owned_library,
        owned_user,
        session.pk,
        saying=(
            "That playthrough was removed from your library. Restore it "
            "before changing its sessions."
        ),
    )

    dispatch(
        RestorePlaythrough(playthrough_id=second.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="restore-run",
    )
    result = restores(owned_library, owned_user, session.pk)

    assert result.outcome is CommandOutcome.APPENDED
    assert PlayerSession.objects.alive().get() == session


def a_session_naming_a_foreign_run(library, foreign_library) -> PlayerSession:
    """Rows, not events: the drift the ownership audit reports."""
    foreign = a_session_another_library_holds(foreign_library)
    return PlayerSession.objects.create(
        id=uuid.uuid7(),
        library=library,
        playthrough=foreign.playthrough,
        timing_mode=PlayerSessionTimingMode.TIMED,
        started_at=START,
        day_zone="Europe/Prague",
        note="",
        emulated=False,
        created_at=timezone.now(),
    )


@pytest.mark.parametrize(
    "statement",
    [
        lambda session, target: EndSession(
            session_id=session.pk, ended_at=AN_END, ended_at_zone=None
        ),
        lambda session, target: CorrectSessionTiming(
            session_id=session.pk, timing=a_duration_only()
        ),
        lambda session, target: DescribeSession(session_id=session.pk, note="late"),
        lambda session, target: MoveSessionToPlaythrough(
            session_id=session.pk, playthrough_id=target.pk
        ),
        lambda session, target: RemoveSession(session_id=session.pk),
        lambda session, target: RestoreSession(session_id=session.pk),
    ],
    ids=["end", "correct", "describe", "move", "remove", "restore"],
)
def test_a_session_naming_a_foreign_run_is_refused_by_name(
    owned_user, owned_library, second_library, run, statement
):
    """Person names session; argument names the run."""
    session = a_session_naming_a_foreign_run(owned_library, second_library)
    if isinstance(statement(session, run), RestoreSession):
        PlayerSession.objects.filter(pk=session.pk).update(removed_at=timezone.now())

    with pytest.raises(RowUnreadable) as refusal:
        dispatch(
            statement(session, run),
            actor=owned_user,
            library=owned_library,
            idempotency_key=str(uuid.uuid7()),
        )

    #: The argument is the log: name everything.
    assert str(session.pk) in str(refusal.value)
    assert str(session.library_id) in str(refusal.value)
    assert str(session.playthrough_id) in str(refusal.value)
    assert refusal.value.__cause__ is not None


def test_a_restored_session_records_a_fact_again(owned_user, owned_library, run):
    session = record(owned_library, owned_user, run, a_timed())
    removes(owned_library, owned_user, session.pk)
    restores(owned_library, owned_user, session.pk)

    ends(owned_library, owned_user, session, ended_at=AN_END)

    assert session.ended_at == AN_END


# --- Instants a calendar cannot hold ------------------------------------------

#: Ten past the last UTC hour Python can hold, stated five hours west.
BEYOND_UTC = datetime(9999, 12, 31, 23, tzinfo=dt_timezone(timedelta(hours=-5)))
#: A UTC instant whose day in Kiritimati is year 10000.
BEYOND_KIRITIMATI = datetime(9999, 12, 31, 20, tzinfo=UTC)
OUT_OF_RANGE = "That time is outside the range we can record."


@pytest.mark.parametrize(
    "construct",
    [
        lambda: CreateSession(
            playthrough_id=uuid.uuid7(), timing=a_timed(started_at=BEYOND_UTC)
        ),
        lambda: CorrectSessionTiming(
            session_id=uuid.uuid7(), timing=a_corrected(ended_at=BEYOND_UTC)
        ),
        lambda: EndSession(
            session_id=uuid.uuid7(), ended_at=BEYOND_UTC, ended_at_zone=None
        ),
    ],
    ids=["create", "correct", "end"],
)
def test_an_instant_utc_cannot_hold_is_refused_at_construction(construct):
    with pytest.raises(CommandRejected) as refusal:
        construct()

    assert refusal.value.sentence == OUT_OF_RANGE


def test_a_start_its_day_zone_cannot_hold_is_refused(owned_user, owned_library, run):
    session = record(owned_library, owned_user, run, a_timed())

    refused_correction(
        owned_library,
        owned_user,
        session.pk,
        a_timed(started_at=BEYOND_KIRITIMATI, day_zone="Pacific/Kiritimati"),
        saying=OUT_OF_RANGE,
    )


def test_an_end_its_own_zone_cannot_hold_is_refused(owned_user, owned_library, run):
    refusal = refused(
        owned_library,
        owned_user,
        run,
        a_timed(ended_at=BEYOND_KIRITIMATI, ended_at_zone="Pacific/Kiritimati"),
    )

    assert refusal.sentence == OUT_OF_RANGE


def test_an_end_its_day_zone_cannot_hold_is_refused(
    owned_user, owned_library, run, set_user_setting
):
    set_user_setting(owned_user, "DISPLAY_TIME_ZONE", "Pacific/Kiritimati")
    session = record(
        owned_library,
        owned_user,
        run,
        a_timed(
            started_at=datetime(9999, 12, 31, 9, tzinfo=UTC),
            day_zone="Pacific/Kiritimati",
        ),
    )

    refused_end(
        owned_library,
        owned_user,
        session.pk,
        ended_at=BEYOND_KIRITIMATI,
        saying=OUT_OF_RANGE,
    )


def test_a_command_with_two_keys_takes_them_by_name():
    """Swapped positional keys would type-check."""
    with pytest.raises(TypeError):
        MoveSessionToPlaythrough(uuid.uuid7(), uuid.uuid7())  # type: ignore[misc]
    with pytest.raises(TypeError):
        CreateSession(uuid.uuid7(), a_timed())  # type: ignore[misc]


def test_it_refuses_recording_a_session_on_the_bucket(owned_user, owned_library, run):
    history = Playthrough.objects.create(
        id=uuid.uuid7(),
        library=owned_library,
        player_game=run.player_game,
        kind=PlaythroughKind.IMPORTED_HISTORY,
        created_at=timezone.now(),
    )

    refusal = refused(owned_library, owned_user, history, a_timed())

    assert refusal.sentence == INTO_THE_BUCKET
    assert not PlayerSession.objects.exists()
