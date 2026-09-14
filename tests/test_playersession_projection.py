"""One row per session a library records."""

import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.apps import apps as global_apps
from django.db import DataError, IntegrityError, models, transaction
from django.utils import timezone

from games.checks import check_projection_models
from games.commands.playergame import TrackGame
from games.events.append import lock_stream
from games.events.dispatch import dispatch
from games.events.playersession import (
    instant_text,
    playersession_created,
    playersession_ended,
)
from games.events.projection import DEFAULT_REGISTRY
from games.events.rebuild import RebuildMode, rebuild_projections
from games.events.references import capture_reference
from games.events.replay import replay
from games.models import (
    Device,
    Game,
    PlayerGame,
    PlayerSession,
    PlayerSessionTimingMode,
    Playthrough,
    PlaythroughKind,
)
from games.preflight.session import MODE_VERDICTS
from games.projections import (
    AUDITED_PROJECTION_REFERENCES,
    unaudited_projection_references,
)
from games.projectors.playersession import columns_for_timing

#: Nothing here wants the row the fixture tracks for a new game.
pytestmark = pytest.mark.untracked_games

START = datetime(2026, 1, 1, 23, 30, tzinfo=UTC)


@pytest.fixture
def game(owned_library):
    return Game.objects.create(library=owned_library, name="Outer Wilds")


@pytest.fixture
def tracked(owned_library, game) -> PlayerGame:
    return PlayerGame.objects.create(
        id=uuid.uuid7(),
        library=owned_library,
        game=game,
        tracked_at=timezone.now(),
    )


@pytest.fixture
def run(owned_library, tracked) -> Playthrough:
    return Playthrough.objects.create(
        id=uuid.uuid7(),
        library=owned_library,
        player_game=tracked,
        kind=PlaythroughKind.ORDINARY,
        created_at=timezone.now(),
    )


def a_session(run: Playthrough, **columns) -> PlayerSession:
    """One row, written the way the projector writes it."""
    stated = {
        "id": uuid.uuid7(),
        "library": run.library,
        "playthrough": run,
        "device": None,
        "timing_mode": PlayerSessionTimingMode.TIMED,
        "started_at": None,
        "started_at_zone": None,
        "ended_at": None,
        "ended_at_zone": None,
        "stated_day": None,
        "stated_duration": None,
        "day_zone": None,
        "note": "",
        "emulated": False,
        "created_at": timezone.now(),
    } | columns
    return PlayerSession.objects.create(**stated)


def a_timed(run: Playthrough, **columns) -> PlayerSession:
    return a_session(
        run,
        **{
            "timing_mode": PlayerSessionTimingMode.TIMED,
            "started_at": START,
            "day_zone": "Europe/Prague",
        }
        | columns,
    )


def a_duration_only(run: Playthrough, **columns) -> PlayerSession:
    return a_session(
        run,
        **{
            "timing_mode": PlayerSessionTimingMode.DURATION_ONLY,
            "stated_day": date(2026, 3, 5),
            "stated_duration": timedelta(minutes=90),
        }
        | columns,
    )


def a_corrected(run: Playthrough, **columns) -> PlayerSession:
    return a_session(
        run,
        **{
            "timing_mode": PlayerSessionTimingMode.CORRECTED,
            "started_at": START,
            "ended_at": START + timedelta(hours=1),
            "stated_duration": timedelta(minutes=30),
            "day_zone": "Europe/Prague",
        }
        | columns,
    )


def refused(constraint, write, *args, **columns) -> None:
    """The named constraint turns this row away.

    The name is stated because several rules overlap: a Timed row
    with no zone breaks its own mode's rule and leaves no day
    behind either, and PostgreSQL reports whichever it reaches
    first. Without the name a test passes while the clause it was
    written for is gone.
    """
    with pytest.raises(IntegrityError, match=constraint), transaction.atomic():
        write(*args, **columns)


def refused_as_data(write, *args, **columns) -> None:
    """Turned away while a generated column is computed.

    Generation runs before any constraint, so a zone PostgreSQL
    cannot read never reaches one.
    """
    with pytest.raises(DataError), transaction.atomic():
        write(*args, **columns)


@pytest.mark.django_db
def test_timed_refuses_a_stated_day(run):
    refused("playersession_timed_columns", a_timed, run, stated_day=date(2026, 1, 1))


@pytest.mark.django_db
def test_timed_refuses_a_stated_duration(run):
    refused(
        "playersession_timed_columns",
        a_timed,
        run,
        stated_duration=timedelta(minutes=5),
    )


@pytest.mark.django_db
def test_timed_requires_a_day_zone(run):
    """The backstop answers, not the mode's own rule.

    A timed row with no zone reads no day, so the row breaks two
    rules and PostgreSQL reports the one it reaches first. This is
    the only case that exercises the backstop at all, since the
    three mode rules leave it nothing else to catch.
    """
    refused("playersession_effective_day_stated", a_timed, run, day_zone=None)


@pytest.mark.django_db
def test_corrected_refuses_a_stated_day(run):
    refused(
        "playersession_corrected_columns", a_corrected, run, stated_day=date(2026, 1, 1)
    )


@pytest.mark.django_db
def test_corrected_requires_both_instants(run):
    refused("playersession_corrected_columns", a_corrected, run, ended_at=None)


@pytest.mark.django_db
def test_corrected_requires_an_override(run):
    refused("playersession_corrected_columns", a_corrected, run, stated_duration=None)


@pytest.mark.django_db
def test_duration_only_refuses_an_instant(run):
    refused(
        "playersession_duration_only_columns", a_duration_only, run, started_at=START
    )


@pytest.mark.django_db
def test_duration_only_refuses_a_day_zone(run):
    refused(
        "playersession_duration_only_columns",
        a_duration_only,
        run,
        day_zone="Europe/Prague",
    )


@pytest.mark.django_db
def test_duration_only_requires_a_duration(run):
    refused(
        "playersession_duration_only_columns",
        a_duration_only,
        run,
        stated_duration=None,
    )


@pytest.mark.django_db
def test_an_endpoint_zone_needs_its_instant(run):
    refused(
        "playersession_zone_needs_its_instant",
        a_timed,
        run,
        ended_at=None,
        ended_at_zone="Asia/Tokyo",
    )


@pytest.mark.django_db
def test_a_blank_day_zone_is_refused(run):
    refused_as_data(a_timed, run, day_zone="")


@pytest.mark.django_db
def test_a_day_zone_no_tzdata_knows_is_refused(run):
    refused_as_data(a_timed, run, day_zone="Not/AZone")


@pytest.mark.django_db
def test_a_blank_start_zone_is_refused(run):
    refused("playersession_zone_not_blank", a_timed, run, started_at_zone="")


@pytest.mark.django_db
def test_a_blank_end_zone_is_refused(run):
    refused(
        "playersession_zone_not_blank",
        a_timed,
        run,
        ended_at=START + timedelta(hours=1),
        ended_at_zone="",
    )


@pytest.mark.django_db
def test_an_end_before_its_start_is_refused(run):
    refused(
        "playersession_end_after_start",
        a_timed,
        run,
        ended_at=START - timedelta(hours=1),
    )


@pytest.mark.django_db
def test_a_negative_duration_is_refused(run):
    refused(
        "playersession_duration_not_negative",
        a_duration_only,
        run,
        stated_duration=timedelta(minutes=-5),
    )


@pytest.mark.django_db
def test_an_unknown_mode_is_refused(run):
    refused("playersession_timing_mode_known", a_timed, run, timing_mode="guessed")


@pytest.mark.django_db
def test_an_end_equal_to_its_start_is_admitted(run):
    session = a_timed(run, ended_at=START)

    session.refresh_from_db()
    assert session.effective_duration == timedelta(0)


@pytest.mark.django_db
def test_a_running_timed_row_is_admitted(run):
    session = a_timed(run)

    session.refresh_from_db()
    assert session.ended_at is None


@pytest.mark.django_db
def test_a_timed_row_takes_its_day_from_its_zone(run):
    session = a_timed(run)

    session.refresh_from_db()
    #: 23:30 UTC is half past midnight in Prague.
    assert session.effective_day == date(2026, 1, 2)
    assert session.sort_instant == START


@pytest.mark.django_db
def test_restating_the_zone_moves_the_day(run):
    session = a_timed(run)

    PlayerSession.objects.filter(pk=session.pk).update(day_zone="UTC")

    session.refresh_from_db()
    assert session.effective_day == date(2026, 1, 1)


@pytest.mark.django_db
def test_a_duration_only_row_takes_its_written_day(run):
    session = a_duration_only(run)

    session.refresh_from_db()
    assert session.effective_day == date(2026, 3, 5)
    assert session.sort_instant == datetime(2026, 3, 5, tzinfo=UTC)
    assert session.effective_duration == timedelta(minutes=90)


@pytest.mark.django_db
def test_a_finished_timed_row_measures_elapsed_time(run):
    session = a_timed(run, ended_at=START + timedelta(hours=2))

    session.refresh_from_db()
    assert session.effective_duration == timedelta(hours=2)


@pytest.mark.django_db
def test_a_running_timed_row_measures_nothing(run):
    session = a_timed(run)

    session.refresh_from_db()
    assert session.effective_duration == timedelta(0)


@pytest.mark.django_db
def test_a_corrected_row_answers_its_override(run):
    session = a_corrected(run)

    session.refresh_from_db()
    #: One hour elapsed, and the override replaces it.
    assert session.effective_duration == timedelta(minutes=30)
    #: The other two columns read a corrected row as they read a
    #: timed one, which is a promise rather than a coincidence.
    assert session.effective_day == date(2026, 1, 2)
    assert session.sort_instant == START


@pytest.mark.django_db
def test_the_table_states_the_rules_it_was_built_with(run):
    """The names, so a migration cannot drop one in silence."""
    assert {constraint.name for constraint in PlayerSession._meta.constraints} == {
        "playersession_timing_mode_known",
        "playersession_timed_columns",
        "playersession_duration_only_columns",
        "playersession_corrected_columns",
        "playersession_end_after_start",
        "playersession_duration_not_negative",
        "playersession_zone_needs_its_instant",
        "playersession_zone_not_blank",
        "playersession_effective_day_stated",
    }
    assert {index.name for index in PlayerSession._meta.indexes} == {
        "playersession_day_order",
        "playersession_sort_order",
        "playersession_run_day",
    }
    #: Ordering is not day-grained, so it keys on the instant.
    assert PlayerSession._meta.get_latest_by == "sort_instant"


@pytest.mark.django_db
def test_no_cascade_may_destroy_a_projection_row():
    for field_name in ("playthrough", "device"):
        field = PlayerSession._meta.get_field(field_name)
        assert field.remote_field.on_delete is models.RESTRICT


@pytest.mark.django_db
def test_the_model_passes_the_projection_checks():
    assert check_projection_models(apps=global_apps) == []


@pytest.mark.django_db
def test_both_references_are_registered():
    keys = {reference.key for reference in AUDITED_PROJECTION_REFERENCES}

    assert ("games.PlayerSession", "playthrough") in keys
    assert ("games.PlayerSession", "device") in keys
    assert unaudited_projection_references() == ()


def test_the_manager_states_alive():
    #: BlockingReferrer.on refuses a model whose manager lacks it.
    assert hasattr(PlayerSession._default_manager, "alive")


@pytest.mark.django_db
def test_a_removed_session_leaves_the_reads(run):
    session = a_timed(run)

    PlayerSession.objects.filter(pk=session.pk).update(removed_at=timezone.now())

    assert not PlayerSession.objects.alive().exists()


@pytest.mark.django_db
def test_a_removed_run_takes_its_sessions_with_it(run):
    a_timed(run)

    Playthrough.objects.filter(pk=run.pk).update(removed_at=timezone.now())

    assert not PlayerSession.objects.alive().exists()


@pytest.mark.django_db
def test_a_removed_tracked_game_takes_its_sessions_with_it(run, tracked):
    a_timed(run)

    PlayerGame.objects.filter(pk=tracked.pk).update(removed_at=timezone.now())

    assert not PlayerSession.objects.alive().exists()


@pytest.mark.django_db
def test_a_removed_catalog_game_leaves_its_sessions_in_place(run, game):
    """The read layer states this mark, and `alive()` does not.

    `blocking_referrer` reads `alive()` to refuse removing a run
    sessions name. A catalog mark here would hide them from that
    check and make the run removable.
    """
    a_timed(run)

    Game.objects.filter(pk=game.pk).update(removed_at=timezone.now())

    assert PlayerSession.objects.alive().exists()


@pytest.mark.django_db
def test_a_session_may_name_a_device(owned_library, run):
    device = Device.objects.create(library=owned_library, name="Steam Deck")

    session = a_timed(run, device=device)

    session.refresh_from_db()
    assert session.device == device


def test_the_modes_are_spelled_as_the_census_spells_them():
    assert {mode.value for mode in PlayerSessionTimingMode} == {
        verdict.value for verdict in MODE_VERDICTS
    }


# --- The projector -----------------------------------------------------------


def a_timed_statement(**timing) -> dict:
    return {
        "mode": "timed",
        "started_at": instant_text(START),
        "started_at_zone": None,
        "ended_at": None,
        "ended_at_zone": None,
        "day_zone": "Europe/Prague",
    } | timing


A_DURATION_ONLY_STATEMENT = {
    "mode": "duration_only",
    "stated_day": "2026-03-05",
    "duration_seconds": 5400,
}

A_CORRECTED_STATEMENT = {
    "mode": "corrected",
    "started_at": instant_text(START),
    "started_at_zone": "Europe/Prague",
    "ended_at": instant_text(START + timedelta(hours=1)),
    "ended_at_zone": "Europe/Prague",
    "day_zone": "Europe/Prague",
    "duration_seconds": 1800,
}


def append_session(library, actor, run, *, timing, key, **stated):
    """Append one creation event, as dispatch would."""
    with transaction.atomic():
        stream = lock_stream(library)
        return stream.append(
            [
                playersession_created(
                    run.pk,
                    timing=timing,
                    device=stated.get("device"),
                    release=None,
                    note=stated.get("note", ""),
                    emulated=stated.get("emulated", False),
                )
            ],
            actor=actor,
            correlation_id=uuid.uuid7(),
            idempotency_key=key,
        )


def test_the_creation_event_has_a_current_state_handler():
    handlers = DEFAULT_REGISTRY.handlers_for("library.playersession.created")

    assert len(handlers) == 1


@pytest.mark.parametrize(
    ("timing", "mode"),
    [
        (a_timed_statement(), PlayerSessionTimingMode.TIMED),
        (A_DURATION_ONLY_STATEMENT, PlayerSessionTimingMode.DURATION_ONLY),
        (A_CORRECTED_STATEMENT, PlayerSessionTimingMode.CORRECTED),
    ],
    ids=["timed", "duration-only", "corrected"],
)
def test_the_mapper_names_every_timing_column(timing, mode):
    """A column a mode forbids is named as None, never left out."""
    columns = columns_for_timing(timing)

    assert set(columns) == {
        "timing_mode",
        "started_at",
        "started_at_zone",
        "ended_at",
        "ended_at_zone",
        "stated_day",
        "stated_duration",
        "day_zone",
    }
    assert columns["timing_mode"] == mode


def test_the_mapper_reads_a_duration_in_seconds():
    columns = columns_for_timing(A_DURATION_ONLY_STATEMENT)

    assert columns["stated_duration"] == timedelta(minutes=90)
    assert columns["stated_day"] == date(2026, 3, 5)
    assert columns["started_at"] is None
    assert columns["day_zone"] is None


def test_the_mapper_reads_both_instants_of_a_corrected_statement():
    columns = columns_for_timing(A_CORRECTED_STATEMENT)

    assert columns["started_at"] == START
    assert columns["ended_at"] == START + timedelta(hours=1)
    assert columns["stated_duration"] == timedelta(minutes=30)
    assert columns["stated_day"] is None


@pytest.mark.django_db(transaction=True)
def test_the_creation_handler_writes_the_whole_row(owned_user, owned_library, run):
    device = Device.objects.create(library=owned_library, name="Steam Deck")

    append_session(
        owned_library,
        owned_user,
        run,
        timing=a_timed_statement(),
        key="create",
        device=capture_reference(device),
        note="A note",
        emulated=True,
    )

    session = PlayerSession.objects.get()
    assert (session.playthrough, session.library, session.device) == (
        run,
        owned_library,
        device,
    )
    assert (session.note, session.emulated) == ("A note", True)
    assert session.timing_mode == PlayerSessionTimingMode.TIMED
    assert session.effective_day == date(2026, 1, 2)


@pytest.mark.django_db(transaction=True)
def test_a_session_takes_its_identity_and_its_moment_from_the_event(
    owned_user, owned_library, run
):
    result = append_session(
        owned_library, owned_user, run, timing=a_timed_statement(), key="create"
    )

    event = result.events[0]
    session = PlayerSession.objects.get()
    assert session.pk == event.aggregate_id
    assert session.created_at == event.recorded_at


@pytest.mark.django_db(transaction=True)
def test_every_mode_projects(owned_user, owned_library, run):
    for index, timing in enumerate(
        [a_timed_statement(), A_DURATION_ONLY_STATEMENT, A_CORRECTED_STATEMENT]
    ):
        append_session(
            owned_library, owned_user, run, timing=timing, key=f"create-{index}"
        )

    assert set(PlayerSession.objects.values_list("timing_mode", flat=True)) == set(
        PlayerSessionTimingMode.values
    )


@pytest.mark.django_db(transaction=True)
def test_the_projection_replays_from_an_empty_stream(owned_user, owned_library, run):
    for index, timing in enumerate(
        [a_timed_statement(), A_DURATION_ONLY_STATEMENT, A_CORRECTED_STATEMENT]
    ):
        append_session(
            owned_library, owned_user, run, timing=timing, key=f"create-{index}"
        )
    before = list(PlayerSession.objects.order_by("pk").values())

    PlayerSession.objects.all().delete()
    replay(owned_library)

    assert list(PlayerSession.objects.order_by("pk").values()) == before


@pytest.mark.django_db(transaction=True)
def test_a_rebuild_reproduces_every_mode(owned_user, owned_library, game):
    """The shadow table generates what the live one holds.

    Duration-only is the row worth rebuilding: its `sort_instant`
    is the one expression whose cast PostgreSQL refuses when it is
    written any other way.
    """
    dispatch(
        TrackGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="track",
    )
    tracked_run = Playthrough.objects.get(player_game__game=game)
    for index, timing in enumerate(
        [a_timed_statement(), A_DURATION_ONLY_STATEMENT, A_CORRECTED_STATEMENT]
    ):
        append_session(
            owned_library, owned_user, tracked_run, timing=timing, key=f"create-{index}"
        )
    before = list(PlayerSession.objects.order_by("pk").values())

    report = rebuild_projections(owned_library, mode=RebuildMode.CHECK)

    assert [
        (table.only_live, table.only_rebuilt, table.differing)
        for table in report.tables
        if table.table == "games_playersession"
    ] == [(0, 0, 0)]
    assert list(PlayerSession.objects.order_by("pk").values()) == before


@pytest.mark.django_db(transaction=True)
def test_a_rebuild_swaps_the_table_with_an_empty_diff(owned_user, owned_library, game):
    """The generated columns and the projection foreign key.

    The run comes from a command here, not from the fixture: a
    rebuild reproduces every projection row from the events, so a
    run nothing recorded would leave this session naming a key the
    rebuilt table no longer holds.
    """
    dispatch(
        TrackGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="track",
    )
    tracked_run = Playthrough.objects.get(player_game__game=game)
    append_session(
        owned_library, owned_user, tracked_run, timing=a_timed_statement(), key="create"
    )

    report = rebuild_projections(owned_library, mode=RebuildMode.REBUILD)

    assert report.swapped is True
    assert [
        (table.table, table.only_live, table.only_rebuilt, table.differing)
        for table in report.tables
        if table.table == "games_playersession"
    ] == [("games_playersession", 0, 0, 0)]


# --- The end of a running session --------------------------------------------


def append_end(
    library,
    actor,
    session,
    *,
    ended_at,
    key,
    ended_at_zone=None,
    day_zone=None,
):
    """Append one end event, as dispatch would."""
    day_zone = day_zone or ZoneInfo("Europe/Prague")
    with transaction.atomic():
        stream = lock_stream(library)
        return stream.append(
            [
                playersession_ended(
                    session.pk,
                    ended_at=ended_at,
                    ended_at_zone=ended_at_zone,
                    day_zone=day_zone,
                )
            ],
            actor=actor,
            correlation_id=uuid.uuid7(),
            idempotency_key=key,
        )


def test_the_end_event_has_a_current_state_handler():
    handlers = DEFAULT_REGISTRY.handlers_for("library.playersession.ended")

    assert len(handlers) == 1


@pytest.mark.django_db(transaction=True)
def test_the_end_handler_writes_two_columns_and_leaves_the_rest(
    owned_user, owned_library, run
):
    device = Device.objects.create(library=owned_library, name="Steam Deck")
    append_session(
        owned_library,
        owned_user,
        run,
        #: Every column the end must not touch carries a value it
        #: could be told apart from: a default would let a handler
        #: that clobbered one still satisfy the assertion.
        timing=a_timed_statement(started_at_zone="Asia/Tokyo"),
        device=capture_reference(device),
        note="A note the end must not take away",
        emulated=True,
        key="create",
    )
    session = PlayerSession.objects.get()
    untouched = (
        "timing_mode",
        "started_at",
        "started_at_zone",
        "stated_day",
        "stated_duration",
        "day_zone",
        "device_id",
        "note",
        "emulated",
    )
    before = {column: getattr(session, column) for column in untouched}

    append_end(
        owned_library,
        owned_user,
        session,
        ended_at=START + timedelta(hours=2),
        ended_at_zone="Asia/Tokyo",
        key="end",
    )

    session.refresh_from_db()
    assert (session.ended_at, session.ended_at_zone) == (
        START + timedelta(hours=2),
        "Asia/Tokyo",
    )
    assert {column: getattr(session, column) for column in untouched} == before


@pytest.mark.django_db(transaction=True)
def test_an_ended_row_measures_the_elapsed_time(owned_user, owned_library, run):
    append_session(
        owned_library, owned_user, run, timing=a_timed_statement(), key="create"
    )
    session = PlayerSession.objects.get()

    append_end(
        owned_library,
        owned_user,
        session,
        ended_at=START + timedelta(hours=2),
        key="end",
    )

    session.refresh_from_db()
    assert session.effective_duration == timedelta(hours=2)


@pytest.mark.django_db(transaction=True)
def test_an_end_moves_neither_the_sort_instant_nor_the_day(
    owned_user, owned_library, run
):
    """The row dates the session by its start.

    The end here is a full day later, so the rule that reads the end
    would report 2026-01-03.
    """
    append_session(
        owned_library, owned_user, run, timing=a_timed_statement(), key="create"
    )
    session = PlayerSession.objects.get()
    before = (session.sort_instant, session.effective_day)

    append_end(
        owned_library,
        owned_user,
        session,
        ended_at=START + timedelta(days=1),
        key="end",
    )

    session.refresh_from_db()
    assert (session.sort_instant, session.effective_day) == before
    assert session.effective_day == date(2026, 1, 2)


@pytest.mark.django_db(transaction=True)
def test_an_ended_session_replays(owned_user, owned_library, run):
    append_session(
        owned_library, owned_user, run, timing=a_timed_statement(), key="create"
    )
    session = PlayerSession.objects.get()
    append_end(
        owned_library,
        owned_user,
        session,
        ended_at=START + timedelta(hours=2),
        key="end",
    )
    before = list(PlayerSession.objects.order_by("pk").values())

    PlayerSession.objects.all().delete()
    replay(owned_library)

    assert list(PlayerSession.objects.order_by("pk").values()) == before


@pytest.mark.django_db(transaction=True)
def test_a_rebuild_reproduces_an_ended_session(owned_user, owned_library, game):
    dispatch(
        TrackGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="track",
    )
    tracked_run = Playthrough.objects.get(player_game__game=game)
    append_session(
        owned_library, owned_user, tracked_run, timing=a_timed_statement(), key="create"
    )
    session = PlayerSession.objects.get()
    append_end(
        owned_library,
        owned_user,
        session,
        ended_at=START + timedelta(hours=2),
        key="end",
    )
    before = list(PlayerSession.objects.order_by("pk").values())

    report = rebuild_projections(owned_library, mode=RebuildMode.CHECK)

    assert [
        (table.only_live, table.only_rebuilt, table.differing)
        for table in report.tables
        if table.table == "games_playersession"
    ] == [(0, 0, 0)]
    assert list(PlayerSession.objects.order_by("pk").values()) == before
