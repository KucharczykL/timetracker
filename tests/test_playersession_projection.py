"""One row per session a library records."""

import itertools
import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from devices import create_device
from django.apps import apps as global_apps
from django.db import DataError, IntegrityError, models, transaction
from django.utils import timezone

from games.checks import check_projection_models
from games.commands.playergame import TrackGame
from games.events.append import lock_stream
from games.events.dispatch import dispatch
from games.events.envelope import RecordedEvent
from games.events.playersession import (
    instant_text,
    playersession_created,
    playersession_device_changed,
    playersession_emulated_changed,
    playersession_ended,
    playersession_moved,
    playersession_note_changed,
    playersession_reclassified,
    playersession_removed,
    playersession_restored,
    playersession_timing_corrected,
)
from games.events.projection import DEFAULT_REGISTRY
from games.events.rebuild import RebuildMode, rebuild_projections
from games.events.references import capture_reference
from games.events.replay import replay
from games.models import (
    Game,
    HistoricalPlaytime,
    HistoricalPlaytimeProvenance,
    LibraryEvent,
    PlayerGame,
    PlayerSession,
    PlayerSessionTimingMode,
    Playthrough,
    PlaythroughKind,
)
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
        "unique_games_playersession_library_identity",
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
def test_every_reference_is_registered():
    keys = {reference.key for reference in AUDITED_PROJECTION_REFERENCES}

    assert ("games.PlayerSession", "playthrough") in keys
    assert ("games.PlayerSession", "device") in keys
    assert ("games.HistoricalPlaytime", "reclassified_from") in keys
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
    device = create_device(library=owned_library, name="Steam Deck")

    session = a_timed(run, device=device)

    session.refresh_from_db()
    assert session.device == device


def test_the_modes_are_spelled_as_the_payload_discriminator_spells_them():
    assert {mode.value for mode in PlayerSessionTimingMode} == {
        "timed",
        "duration_only",
        "corrected",
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
    device = create_device(library=owned_library, name="Steam Deck")

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
    device = create_device(library=owned_library, name="Steam Deck")
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


# --- Corrections -------------------------------------------------------------


def append_events(library, actor, events, *, key):
    """Append events as one dispatch would."""
    with transaction.atomic():
        stream = lock_stream(library)
        return stream.append(
            events,
            actor=actor,
            correlation_id=uuid.uuid7(),
            idempotency_key=key,
        )


TIMING_STATES = {
    "timed-running": a_timed_statement(),
    "timed-finished": a_timed_statement(
        ended_at=instant_text(START + timedelta(hours=2)), ended_at_zone="Asia/Tokyo"
    ),
    "duration-only": A_DURATION_ONLY_STATEMENT,
    "corrected": A_CORRECTED_STATEMENT,
}

TRANSITIONS = list(itertools.permutations(TIMING_STATES, 2))

TIMING_COLUMNS = (
    "timing_mode",
    "started_at",
    "started_at_zone",
    "ended_at",
    "ended_at_zone",
    "stated_day",
    "stated_duration",
    "day_zone",
)

DESCRIPTION_COLUMNS = ("note", "device_id", "emulated")


def columns_of(session: PlayerSession, names) -> dict:
    return {name: getattr(session, name) for name in names}


@pytest.mark.parametrize(
    "event_type",
    [
        "library.playersession.timing_corrected",
        "library.playersession.note_changed",
        "library.playersession.device_changed",
        "library.playersession.emulated_changed",
        "library.playersession.moved",
    ],
)
def test_every_correction_has_a_current_state_handler(event_type):
    assert len(DEFAULT_REGISTRY.handlers_for(event_type)) == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("before", "after"),
    TRANSITIONS,
    ids=[f"{before}->{after}" for before, after in TRANSITIONS],
)
def test_every_transition_projects(owned_user, owned_library, run, before, after):
    """No old mode stays; every CHECK admits it."""
    append_session(
        owned_library, owned_user, run, timing=TIMING_STATES[before], key="create"
    )
    session = PlayerSession.objects.get()

    append_events(
        owned_library,
        owned_user,
        [playersession_timing_corrected(session.pk, timing=TIMING_STATES[after])],
        key="correct",
    )

    session.refresh_from_db()
    assert columns_of(session, TIMING_COLUMNS) == columns_for_timing(
        TIMING_STATES[after]
    )
    expected = {
        "timed-running": (date(2026, 1, 2), timedelta(0)),
        "timed-finished": (date(2026, 1, 2), timedelta(hours=2)),
        "duration-only": (date(2026, 3, 5), timedelta(minutes=90)),
        "corrected": (date(2026, 1, 2), timedelta(minutes=30)),
    }[after]
    assert (session.effective_day, session.effective_duration) == expected


@pytest.mark.django_db(transaction=True)
def test_a_timing_correction_leaves_the_description_and_the_run(
    owned_user, owned_library, run
):
    device = create_device(library=owned_library, name="Steam Deck")
    append_session(
        owned_library,
        owned_user,
        run,
        timing=a_timed_statement(),
        device=capture_reference(device),
        note="A note the correction must not take away",
        emulated=True,
        key="create",
    )
    session = PlayerSession.objects.get()
    untouched = (*DESCRIPTION_COLUMNS, "playthrough_id", "created_at")
    before = columns_of(session, untouched)

    append_events(
        owned_library,
        owned_user,
        [playersession_timing_corrected(session.pk, timing=A_CORRECTED_STATEMENT)],
        key="correct",
    )

    session.refresh_from_db()
    assert columns_of(session, untouched) == before


@pytest.mark.django_db(transaction=True)
def test_each_description_event_writes_its_own_column(owned_user, owned_library, run):
    old_device = create_device(library=owned_library, name="Steam Deck")
    new_device = create_device(library=owned_library, name="Switch")
    append_session(
        owned_library,
        owned_user,
        run,
        timing=a_timed_statement(started_at_zone="Asia/Tokyo"),
        device=capture_reference(old_device),
        note="before",
        emulated=False,
        key="create",
    )
    session = PlayerSession.objects.get()
    timing_before = columns_of(session, TIMING_COLUMNS)
    steps = [
        (playersession_note_changed(session.pk, note="after"), "note", "after"),
        (
            playersession_device_changed(
                session.pk, device=capture_reference(new_device)
            ),
            "device_id",
            new_device.pk,
        ),
        (playersession_emulated_changed(session.pk, emulated=True), "emulated", True),
        (playersession_device_changed(session.pk, device=None), "device_id", None),
    ]

    for index, (event, column, value) in enumerate(steps):
        others = [name for name in DESCRIPTION_COLUMNS if name != column]
        session.refresh_from_db()
        others_before = columns_of(session, others)

        append_events(owned_library, owned_user, [event], key=f"step-{index}")

        session.refresh_from_db()
        assert getattr(session, column) == value
        assert columns_of(session, others) == others_before
        assert columns_of(session, TIMING_COLUMNS) == timing_before


@pytest.mark.django_db(transaction=True)
def test_a_move_names_a_run_at_another_game(owned_user, owned_library, run):
    other_game = Game.objects.create(library=owned_library, name="Tunic")
    other_tracked = PlayerGame.objects.create(
        id=uuid.uuid7(),
        library=owned_library,
        game=other_game,
        tracked_at=timezone.now(),
    )
    other_run = Playthrough.objects.create(
        id=uuid.uuid7(),
        library=owned_library,
        player_game=other_tracked,
        kind=PlaythroughKind.ORDINARY,
        created_at=timezone.now(),
    )
    append_session(
        owned_library, owned_user, run, timing=a_timed_statement(), key="create"
    )
    session = PlayerSession.objects.get()
    timing_before = columns_of(session, TIMING_COLUMNS)

    append_events(
        owned_library,
        owned_user,
        [playersession_moved(session.pk, playthrough_id=other_run.pk)],
        key="move",
    )

    session.refresh_from_db()
    assert session.playthrough_id == other_run.pk
    assert session.playthrough.player_game.game == other_game
    assert columns_of(session, TIMING_COLUMNS) == timing_before
    assert PlayerSession.objects.alive().filter(pk=session.pk).exists()


def correct_everything(library, actor, session, *, device, target):
    """One of every correction, each its own dispatch."""
    events = [
        playersession_timing_corrected(session.pk, timing=A_CORRECTED_STATEMENT),
        playersession_note_changed(session.pk, note="corrected"),
        playersession_device_changed(session.pk, device=capture_reference(device)),
        playersession_emulated_changed(session.pk, emulated=True),
        playersession_moved(session.pk, playthrough_id=target.pk),
    ]
    for index, event in enumerate(events):
        append_events(library, actor, [event], key=f"correction-{index}")


def assert_every_correction_landed(session, *, device, target) -> None:
    """Else a replay comparison passes with no handler."""
    session.refresh_from_db()
    assert (
        session.timing_mode,
        session.note,
        session.device_id,
        session.emulated,
        session.playthrough_id,
    ) == (PlayerSessionTimingMode.CORRECTED, "corrected", device.pk, True, target.pk)


@pytest.mark.django_db(transaction=True)
def test_a_corrected_session_replays(owned_user, owned_library, run, game):
    other_game = Game.objects.create(library=owned_library, name="Tunic")
    dispatch(
        TrackGame(game_id=other_game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="track-other",
    )
    target = Playthrough.objects.get(player_game__game=other_game)
    device = create_device(library=owned_library, name="Steam Deck")
    append_session(
        owned_library, owned_user, run, timing=a_timed_statement(), key="create"
    )
    session = PlayerSession.objects.get()
    correct_everything(owned_library, owned_user, session, device=device, target=target)
    assert_every_correction_landed(session, device=device, target=target)
    before = list(PlayerSession.objects.order_by("pk").values())

    PlayerSession.objects.all().delete()
    replay(owned_library)

    assert list(PlayerSession.objects.order_by("pk").values()) == before
    assert before[0]["playthrough_id"] == target.pk


@pytest.mark.django_db(transaction=True)
def test_a_rebuild_reproduces_a_corrected_session(owned_user, owned_library, game):
    other_game = Game.objects.create(library=owned_library, name="Tunic")
    for tracked_game, key in ((game, "track"), (other_game, "track-other")):
        dispatch(
            TrackGame(game_id=tracked_game.pk),
            actor=owned_user,
            library=owned_library,
            idempotency_key=key,
        )
    source = Playthrough.objects.get(player_game__game=game)
    target = Playthrough.objects.get(player_game__game=other_game)
    device = create_device(library=owned_library, name="Steam Deck")
    append_session(
        owned_library, owned_user, source, timing=a_timed_statement(), key="create"
    )
    session = PlayerSession.objects.get()
    correct_everything(owned_library, owned_user, session, device=device, target=target)
    assert_every_correction_landed(session, device=device, target=target)
    before = list(PlayerSession.objects.order_by("pk").values())

    report = rebuild_projections(owned_library, mode=RebuildMode.CHECK)

    assert [
        (table.only_live, table.only_rebuilt, table.differing)
        for table in report.tables
        if table.table == "games_playersession"
    ] == [(0, 0, 0)]
    assert list(PlayerSession.objects.order_by("pk").values()) == before


# --- Removing and restoring a session ----------------------------------------


def a_recorded_session(library, actor, run) -> PlayerSession:
    append_session(library, actor, run, timing=a_timed_statement(), key="create")
    return PlayerSession.objects.get()


def reapply_creation(identity):
    """Apply the recorded creation event again."""
    event = RecordedEvent.from_row(LibraryEvent.objects.get(aggregate_id=identity))
    with transaction.atomic():
        DEFAULT_REGISTRY.apply(event)


@pytest.mark.parametrize(
    "event_type",
    ["library.playersession.removed", "library.playersession.restored"],
)
def test_the_lifecycle_events_have_a_current_state_handler(event_type):
    assert len(DEFAULT_REGISTRY.handlers_for(event_type)) == 1


@pytest.mark.django_db(transaction=True)
def test_the_removal_event_writes_its_own_time(owned_user, owned_library, run):
    """Off the event, so a replay agrees."""
    session = a_recorded_session(owned_library, owned_user, run)

    append_events(
        owned_library, owned_user, [playersession_removed(session.pk)], key="gone"
    )

    stamped = LibraryEvent.objects.get(
        event_type="library.playersession.removed"
    ).recorded_at
    session.refresh_from_db()
    assert session.removed_at == stamped
    assert not PlayerSession.objects.alive().exists()


@pytest.mark.django_db(transaction=True)
def test_the_restore_event_states_the_way_back(owned_user, owned_library, run):
    session = a_recorded_session(owned_library, owned_user, run)
    append_events(
        owned_library, owned_user, [playersession_removed(session.pk)], key="gone"
    )

    append_events(
        owned_library, owned_user, [playersession_restored(session.pk)], key="back"
    )

    session.refresh_from_db()
    assert session.removed_at is None
    assert PlayerSession.objects.alive().get() == session


@pytest.mark.django_db(transaction=True)
def test_re_applying_the_creation_event_keeps_a_later_removal(
    owned_user, owned_library, run
):
    """The creation handler never names the mark."""
    session = a_recorded_session(owned_library, owned_user, run)
    stamped = timezone.now()
    PlayerSession.objects.filter(pk=session.pk).update(removed_at=stamped)

    reapply_creation(session.pk)

    session.refresh_from_db()
    assert session.removed_at == stamped


@pytest.mark.django_db(transaction=True)
def test_a_replay_reproduces_a_removal_and_its_undoing(owned_user, owned_library, run):
    """Removed, back, removed again: one state."""
    session = a_recorded_session(owned_library, owned_user, run)
    lifecycle = (
        playersession_removed(session.pk),
        playersession_restored(session.pk),
        playersession_removed(session.pk),
    )
    for index, event in enumerate(lifecycle):
        append_events(owned_library, owned_user, [event], key=f"lifecycle-{index}")
    last = (
        LibraryEvent.objects.filter(event_type="library.playersession.removed")
        .order_by("sequence")
        .last()
        .recorded_at
    )
    before = list(PlayerSession.objects.order_by("pk").values())

    PlayerSession.objects.all().delete()
    replay(owned_library)

    assert list(PlayerSession.objects.order_by("pk").values()) == before
    assert PlayerSession.objects.get().removed_at == last


@pytest.mark.django_db(transaction=True)
def test_a_rebuild_reproduces_a_removed_session(owned_user, owned_library, run):
    session = a_recorded_session(owned_library, owned_user, run)
    append_events(
        owned_library, owned_user, [playersession_removed(session.pk)], key="gone"
    )
    before = list(PlayerSession.objects.order_by("pk").values())

    report = rebuild_projections(owned_library, mode=RebuildMode.CHECK)

    assert [
        (table.only_live, table.only_rebuilt, table.differing)
        for table in report.tables
        if table.table == "games_playersession"
    ] == [(0, 0, 0)]
    assert list(PlayerSession.objects.order_by("pk").values()) == before


def a_record(run: Playthrough) -> HistoricalPlaytime:
    """One record row for a session to name."""
    return HistoricalPlaytime.objects.create(
        pk=uuid.uuid7(),
        library=run.library,
        player_game=run.player_game,
        duration=timedelta(hours=3),
        when=None,
        provenance=HistoricalPlaytimeProvenance.MANUALLY_ENTERED,
        device=None,
        emulated=False,
        note="",
        created_at=timezone.now(),
    )


@pytest.mark.django_db(transaction=True)
def test_the_reclassification_marks_the_session_and_names_the_record(
    owned_user, owned_library, run
):
    """One event, one column: the mark."""
    session = a_recorded_session(owned_library, owned_user, run)
    record = a_record(run)

    append_events(
        owned_library,
        owned_user,
        [playersession_reclassified(session.pk, record_id=record.pk)],
        key="became-a-record",
    )

    stamped = LibraryEvent.objects.get(
        event_type="library.playersession.reclassified"
    ).recorded_at
    session.refresh_from_db()
    assert session.removed_at == stamped
    assert not PlayerSession.objects.alive().exists()


@pytest.mark.django_db(transaction=True)
def test_a_restore_clears_the_mark(owned_user, owned_library, run):
    session = a_recorded_session(owned_library, owned_user, run)
    record = a_record(run)
    append_events(
        owned_library,
        owned_user,
        [playersession_reclassified(session.pk, record_id=record.pk)],
        key="became-a-record",
    )

    append_events(
        owned_library, owned_user, [playersession_restored(session.pk)], key="back"
    )

    session.refresh_from_db()
    assert session.removed_at is None


def test_the_reclassification_event_has_a_current_state_handler():
    assert len(DEFAULT_REGISTRY.handlers_for("library.playersession.reclassified")) == 1


@pytest.mark.django_db(transaction=True)
def test_a_replay_reproduces_a_reclassified_session(owned_user, owned_library, run):
    session = a_recorded_session(owned_library, owned_user, run)
    record = a_record(run)
    append_events(
        owned_library,
        owned_user,
        [playersession_reclassified(session.pk, record_id=record.pk)],
        key="became-a-record",
    )
    before = list(PlayerSession.objects.order_by("pk").values())

    PlayerSession.objects.all().delete()
    replay(owned_library)

    assert list(PlayerSession.objects.order_by("pk").values()) == before
