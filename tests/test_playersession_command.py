"""Recording one session against a stated run."""

import uuid
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache

import pytest
from django.utils import timezone

from games.commands.playergame import TrackGame
from games.commands.playersession import (
    CorrectedTiming,
    CreateSession,
    DurationOnlyTiming,
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
    refused(owned_library, owned_user, run, a_timed(day_zone=""))


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
