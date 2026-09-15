"""The zone a library counts days in."""

import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from games.commands.calendar import SetCalendarDayZone
from games.commands.playergame import TrackGame
from games.commands.playersession import (
    CorrectedTiming,
    CreateSession,
    DurationOnlyTiming,
    RemoveSession,
    TimedTiming,
)
from games.events.calendar import CALENDAR_DAY_ZONE_CHANGED
from games.events.dispatch import CommandOutcome, CommandRejected, dispatch
from games.events.rebuild import RebuildMode, rebuild_projections
from games.models import (
    Game,
    LibraryCalendar,
    LibraryEvent,
    PlayerSession,
    Playthrough,
)
from games.reads.calendar import CalendarDelta, calendar_delta, calendar_sentence

#: 00:30 on 2 January in Prague; 23:30 on 1 January in UTC.
START = datetime(2026, 1, 1, 23, 30, tzinfo=UTC)


def set_day_zone(library, actor, zone, *, key=None):
    return dispatch(
        SetCalendarDayZone(day_zone=zone),
        actor=actor,
        library=library,
        idempotency_key=key or str(uuid.uuid7()),
    )


@pytest.fixture
def prague_owner(owned_user, set_user_setting):
    set_user_setting(owned_user, "DISPLAY_TIME_ZONE", "Europe/Prague")
    return owned_user


@pytest.fixture
def run(prague_owner, owned_library) -> Playthrough:
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    dispatch(
        TrackGame(game_id=game.pk),
        actor=prague_owner,
        library=owned_library,
        idempotency_key="track",
    )
    return Playthrough.objects.get(player_game__game=game)


def record(library, actor, run, timing) -> PlayerSession:
    result = dispatch(
        CreateSession(playthrough_id=run.pk, timing=timing),
        actor=actor,
        library=library,
        idempotency_key=str(uuid.uuid7()),
    )
    assert result.sequences is not None
    created = LibraryEvent.objects.get(library=library, sequence=result.sequences.first)
    return PlayerSession.objects.get(pk=created.aggregate_id)


# --- the command ---------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_an_unknown_zone_is_refused(owned_user, owned_library):
    with pytest.raises(CommandRejected) as refusal:
        set_day_zone(owned_library, owned_user, "Not/AZone")
    assert refusal.value.sentence == "Not/AZone is not a time zone we know."
    assert not LibraryEvent.objects.filter(library=owned_library).exists()


@pytest.mark.django_db(transaction=True)
def test_a_blank_zone_is_refused(owned_user, owned_library):
    with pytest.raises(CommandRejected) as refusal:
        set_day_zone(owned_library, owned_user, "  ")
    assert refusal.value.sentence


@pytest.mark.django_db(transaction=True)
def test_the_first_change_writes_the_row(owned_user, owned_library):
    result = set_day_zone(owned_library, owned_user, "Europe/Prague")

    assert result.outcome is CommandOutcome.APPENDED
    row = LibraryCalendar.objects.get(library=owned_library)
    assert row.pk == owned_library.pk
    assert row.day_zone == "Europe/Prague"
    event = LibraryEvent.objects.get(library=owned_library)
    assert event.event_type == CALENDAR_DAY_ZONE_CHANGED.event_type
    assert event.aggregate_id == owned_library.pk
    assert event.payload == {"day_zone": "Europe/Prague"}


@pytest.mark.django_db(transaction=True)
def test_the_same_zone_is_unchanged(owned_user, owned_library):
    set_day_zone(owned_library, owned_user, "Europe/Prague")

    result = set_day_zone(owned_library, owned_user, "Europe/Prague")

    assert result.outcome is CommandOutcome.UNCHANGED
    assert LibraryEvent.objects.filter(library=owned_library).count() == 1


@pytest.mark.django_db(transaction=True)
def test_a_padded_zone_is_the_zone(owned_user, owned_library):
    set_day_zone(owned_library, owned_user, "Europe/Prague")

    result = set_day_zone(owned_library, owned_user, " Europe/Prague ")

    assert result.outcome is CommandOutcome.UNCHANGED


@pytest.mark.django_db(transaction=True)
def test_a_second_zone_replaces_the_first(owned_user, owned_library):
    set_day_zone(owned_library, owned_user, "Europe/Prague")

    result = set_day_zone(owned_library, owned_user, "UTC")

    assert result.outcome is CommandOutcome.APPENDED
    assert LibraryCalendar.objects.get(library=owned_library).day_zone == "UTC"
    assert LibraryCalendar.objects.filter(library=owned_library).count() == 1


# --- the projector's session rewrite -------------------------------------


@pytest.mark.django_db(transaction=True)
def test_a_change_moves_every_timed_and_corrected_day(prague_owner, owned_library, run):
    timed = record(
        owned_library,
        prague_owner,
        run,
        TimedTiming(started_at=START, day_zone="Europe/Prague"),
    )
    corrected = record(
        owned_library,
        prague_owner,
        run,
        CorrectedTiming(
            started_at=START,
            ended_at=START + timedelta(hours=1),
            duration=timedelta(minutes=30),
            day_zone="Europe/Prague",
            started_at_zone="Asia/Tokyo",
        ),
    )
    removed = record(
        owned_library,
        prague_owner,
        run,
        TimedTiming(started_at=START, day_zone="Europe/Prague"),
    )
    dispatch(
        RemoveSession(session_id=removed.pk),
        actor=prague_owner,
        library=owned_library,
        idempotency_key="remove",
    )
    duration_only = record(
        owned_library,
        prague_owner,
        run,
        DurationOnlyTiming(day=date(2026, 3, 5), duration=timedelta(minutes=90)),
    )
    assert timed.effective_day == date(2026, 1, 2)

    set_day_zone(owned_library, prague_owner, "UTC")

    for row in (timed, corrected, removed):
        row.refresh_from_db()
        assert row.day_zone == "UTC"
        assert row.effective_day == date(2026, 1, 1)
    assert corrected.started_at_zone == "Asia/Tokyo"
    duration_only.refresh_from_db()
    assert duration_only.day_zone is None
    assert duration_only.effective_day == date(2026, 3, 5)


@pytest.mark.django_db(transaction=True)
def test_a_change_leaves_another_library_alone(
    prague_owner, owned_library, run, django_user_model
):
    mine = record(
        owned_library,
        prague_owner,
        run,
        TimedTiming(started_at=START, day_zone="Europe/Prague"),
    )
    other = django_user_model.objects.create_user(username="second-owner")
    set_day_zone(other.library, other, "UTC")

    mine.refresh_from_db()
    assert mine.day_zone == "Europe/Prague"


@pytest.mark.untracked_games
@pytest.mark.django_db(transaction=True)
def test_a_replay_reproduces_the_rewritten_days(prague_owner, owned_library, run):
    record(
        owned_library,
        prague_owner,
        run,
        TimedTiming(started_at=START, day_zone="Europe/Prague"),
    )
    set_day_zone(owned_library, prague_owner, "UTC")

    report = rebuild_projections(owned_library, mode=RebuildMode.CHECK)

    for table in report.tables:
        assert (table.only_live, table.only_rebuilt, table.differing) == (0, 0, 0), (
            table
        )


# --- the read --------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_the_read_answers_the_row(owned_user, owned_library):
    from games.reads.calendar import calendar_day_zone

    set_day_zone(owned_library, owned_user, "Asia/Tokyo")

    assert calendar_day_zone(owned_library) == ZoneInfo("Asia/Tokyo")


@pytest.mark.django_db
def test_the_read_answers_the_owners_zone_without_a_row(
    owned_user, owned_library, set_user_setting
):
    from games.reads.calendar import calendar_day_zone

    set_user_setting(owned_user, "DISPLAY_TIME_ZONE", "Europe/Prague")

    assert calendar_day_zone(owned_library) == ZoneInfo("Europe/Prague")


# --- the delta ---------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_the_delta_counts_the_days_months_and_years_that_move(
    prague_owner, owned_library, run
):
    def timed(started_at):
        return TimedTiming(started_at=started_at, day_zone="Europe/Prague")

    #: Prague 2 January; UTC 1 January. Day only.
    record(owned_library, prague_owner, run, timed(START))
    #: Prague 1 February; UTC 31 January. Month too.
    record(
        owned_library,
        prague_owner,
        run,
        timed(datetime(2026, 1, 31, 23, 30, tzinfo=UTC)),
    )
    #: Prague 1 January 2026; UTC 31 December 2025. Year too.
    record(
        owned_library,
        prague_owner,
        run,
        timed(datetime(2025, 12, 31, 23, 30, tzinfo=UTC)),
    )
    #: Noon: no move.
    record(
        owned_library,
        prague_owner,
        run,
        timed(datetime(2026, 1, 15, 12, 0, tzinfo=UTC)),
    )
    removed = record(owned_library, prague_owner, run, timed(START))
    dispatch(
        RemoveSession(session_id=removed.pk),
        actor=prague_owner,
        library=owned_library,
        idempotency_key="remove",
    )
    record(
        owned_library,
        prague_owner,
        run,
        DurationOnlyTiming(day=date(2026, 3, 5), duration=timedelta(minutes=90)),
    )

    delta = calendar_delta(owned_library, "UTC")

    assert delta == CalendarDelta(
        day_zone="UTC", sessions=4, day_moved=3, month_moved=2, year_moved=1
    )
    assert calendar_delta(owned_library, "Europe/Prague") == CalendarDelta(
        day_zone="Europe/Prague", sessions=4, day_moved=0, month_moved=0, year_moved=0
    )


def test_deltas_add_up():
    first = CalendarDelta("UTC", 2807, 124, 10, 5)
    second = CalendarDelta("UTC", 3, 2, 1, 0)

    assert first + second == CalendarDelta("UTC", 2810, 126, 11, 5)


def test_the_sentence_reads_the_delta():
    delta = CalendarDelta("UTC", 2807, 124, 10, 5)

    assert calendar_sentence(delta) == (
        "Days now counted in UTC: 2,807 sessions, 124 moved to another day, "
        "10 to another month, 5 to another year."
    )
