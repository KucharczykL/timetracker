"""One row per historical playtime record."""

import uuid
from datetime import date, timedelta

import pytest
from django.apps import apps as global_apps
from django.db import IntegrityError, transaction
from django.utils import timezone
from session_rows import duration_only_row

from games.checks import check_projection_models
from games.commands.playergame import TrackGame
from games.events.append import lock_stream
from games.events.dispatch import dispatch
from games.events.historical_playtime import (
    historicalplaytime_created,
    historicalplaytime_removed,
    historicalplaytime_restated,
    historicalplaytime_restored,
)
from games.events.rebuild import RebuildMode, rebuild_projections
from games.events.replay import replay
from games.models import (
    Game,
    HistoricalPlaytime,
    HistoricalPlaytimeProvenance,
    HistoricalPlaytimeRun,
    LibraryEvent,
    PlayerGame,
    Playthrough,
    PlaythroughKind,
)
from games.projections import (
    AUDITED_PROJECTION_REFERENCES,
    unaudited_projection_references,
)
from games.projectors.historical_playtime import columns_for_statement
from timetracker.temporal import TemporalValue

#: No fixture-tracked row wanted here.
pytestmark = pytest.mark.untracked_games


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


def a_record(tracked, **stated) -> HistoricalPlaytime:
    """One row, as the projector writes it."""
    columns = {
        "id": uuid.uuid7(),
        "library": tracked.library,
        "player_game": tracked,
        "duration": timedelta(hours=100),
        "when": "2005",
        "provenance": HistoricalPlaytimeProvenance.ESTIMATED,
        "device": None,
        "emulated": False,
        "note": "",
        "created_at": timezone.now(),
    } | stated
    return HistoricalPlaytime.objects.create(**columns)


def a_join(record, run) -> HistoricalPlaytimeRun:
    return HistoricalPlaytimeRun.objects.create(
        id=uuid.uuid7(), library=record.library, record=record, playthrough=run
    )


@pytest.mark.django_db
def test_a_zero_duration_is_refused(tracked):
    with pytest.raises(IntegrityError), transaction.atomic():
        a_record(tracked, duration=timedelta(0))


@pytest.mark.django_db
def test_a_negative_duration_is_refused(tracked):
    with pytest.raises(IntegrityError), transaction.atomic():
        a_record(tracked, duration=timedelta(hours=-1))


@pytest.mark.django_db
def test_an_unknown_provenance_is_refused(tracked):
    with pytest.raises(IntegrityError), transaction.atomic():
        a_record(tracked, provenance="guessed")


@pytest.mark.django_db
def test_a_run_is_named_once_per_record(tracked, run):
    record = a_record(tracked)
    a_join(record, run)
    with pytest.raises(IntegrityError), transaction.atomic():
        a_join(record, run)


@pytest.mark.django_db
def test_an_unknown_when_is_admitted(tracked):
    record = a_record(tracked, when=None)
    record.refresh_from_db()
    assert record.when is None
    assert record.when_lower is None
    assert record.when_upper is None


@pytest.mark.django_db
def test_a_year_bounds_to_its_first_and_last_day(tracked):
    record = a_record(tracked, when="2005")
    record.refresh_from_db()
    assert record.when_lower == date(2005, 1, 1)
    assert record.when_upper == date(2005, 12, 31)


@pytest.mark.django_db
def test_an_open_range_has_no_upper_bound(tracked):
    record = a_record(tracked, when="2005/")
    record.refresh_from_db()
    assert record.when_lower == date(2005, 1, 1)
    assert record.when_upper is None


def test_the_model_passes_the_projection_checks():
    assert check_projection_models(apps=global_apps) == []


def test_the_four_references_are_registered():
    keys = {reference.key for reference in AUDITED_PROJECTION_REFERENCES}
    assert ("games.HistoricalPlaytime", "player_game") in keys
    assert ("games.HistoricalPlaytime", "device") in keys
    assert ("games.HistoricalPlaytimeRun", "record") in keys
    assert ("games.HistoricalPlaytimeRun", "playthrough") in keys
    assert unaudited_projection_references() == ()


def test_both_managers_state_alive():
    assert hasattr(HistoricalPlaytime._default_manager, "alive")
    assert hasattr(HistoricalPlaytimeRun._default_manager, "alive")


@pytest.mark.django_db
def test_a_removed_record_hides_its_join_rows(tracked, run):
    record = a_record(tracked)
    a_join(record, run)
    HistoricalPlaytime.objects.filter(pk=record.pk).update(removed_at=timezone.now())
    assert not HistoricalPlaytimeRun.objects.alive().exists()


@pytest.mark.django_db
def test_a_removed_tracked_game_hides_the_record(tracked, run):
    record = a_record(tracked)
    a_join(record, run)
    PlayerGame.objects.filter(pk=tracked.pk).update(removed_at=timezone.now())
    assert not HistoricalPlaytime.objects.alive().exists()
    assert not HistoricalPlaytimeRun.objects.alive().exists()


def test_the_record_reaches_the_game_in_one_hop():
    assert HistoricalPlaytime.comparison_through == (("player_game__game", "Game"),)


# --- The projector -----------------------------------------------------------


def append(library, actor, event, *, key: str) -> None:
    """Append one event under a key."""
    with transaction.atomic():
        stream = lock_stream(library)
        stream.append(
            [event], actor=actor, correlation_id=uuid.uuid7(), idempotency_key=key
        )


def a_created(tracked, runs, **stated):
    return historicalplaytime_created(
        player_game_id=tracked.pk,
        runs=[{"id": str(uuid.uuid7()), "playthrough": str(run.pk)} for run in runs],
        duration=stated.get("duration", timedelta(hours=100)),
        when=stated.get("when", TemporalValue.parse("2005")),
        provenance=stated.get("provenance", "estimated"),
        device=stated.get("device"),
        emulated=stated.get("emulated", False),
        note=stated.get("note", ""),
    )


@pytest.mark.django_db(transaction=True)
def test_a_restatement_marks_the_row_and_a_second_moves_the_mark(
    owned_user, owned_library, tracked, run
):
    created = a_created(tracked, [run])
    append(owned_library, owned_user, created, key="create")
    assert HistoricalPlaytime.objects.get().restated_at is None

    def restated(note: str):
        return historicalplaytime_restated(
            created.aggregate_id,
            player_game_id=tracked.pk,
            runs=created.payload["playthroughs"],
            duration=timedelta(hours=1),
            when=TemporalValue.parse("2005"),
            provenance="estimated",
            device=None,
            emulated=False,
            note=note,
        )

    append(owned_library, owned_user, restated("once"), key="restate-1")
    first = HistoricalPlaytime.objects.get().restated_at
    append(owned_library, owned_user, restated("twice"), key="restate-2")
    second = HistoricalPlaytime.objects.get().restated_at

    assert first is not None
    assert second is not None
    assert second > first
    assert second == LibraryEvent.objects.latest("sequence").recorded_at


@pytest.mark.django_db(transaction=True)
def test_a_creation_names_the_session_it_came_from(
    owned_user, owned_library, tracked, run
):
    session = duration_only_row(run, date(2026, 3, 5), timedelta(hours=9))
    created = historicalplaytime_created(
        player_game_id=tracked.pk,
        runs=[{"id": str(uuid.uuid7()), "playthrough": str(run.pk)}],
        duration=timedelta(hours=9),
        when=TemporalValue.parse("2026-03-05"),
        provenance="manually_entered",
        device=None,
        emulated=False,
        note="",
        reclassified_from=session.pk,
    )

    append(owned_library, owned_user, created, key="create")

    assert HistoricalPlaytime.objects.get().reclassified_from_id == session.pk
    assert a_record(tracked).reclassified_from_id is None


@pytest.mark.django_db(transaction=True)
def test_the_migration_states_restated_at_as_the_replay_does(
    owned_user, owned_library, tracked, run
):
    """The backfill reads the stream as replay does."""
    import importlib

    from django.db import connection

    migration = importlib.import_module(
        "games.migrations.0011_historicalplaytime_reclassified_from"
    )
    created = a_created(tracked, [run])
    append(owned_library, owned_user, created, key="create")
    for note in ("once", "twice"):
        append(
            owned_library,
            owned_user,
            historicalplaytime_restated(
                created.aggregate_id,
                player_game_id=tracked.pk,
                runs=created.payload["playthroughs"],
                duration=timedelta(hours=1),
                when=TemporalValue.parse("2005"),
                provenance="estimated",
                device=None,
                emulated=False,
                note=note,
            ),
            key=f"restate-{note}",
        )
    replayed = HistoricalPlaytime.objects.get().restated_at
    HistoricalPlaytime.objects.update(restated_at=None)

    with connection.schema_editor() as editor:
        migration.state_restated_at(None, editor)

    assert HistoricalPlaytime.objects.get().restated_at == replayed
    assert replayed is not None


def a_second_run(owned_library, tracked) -> Playthrough:
    return Playthrough.objects.create(
        id=uuid.uuid7(),
        library=owned_library,
        player_game=tracked,
        kind=PlaythroughKind.ORDINARY,
        created_at=timezone.now(),
    )


def test_the_mapper_names_every_statement_column():
    payload = {
        "player_game": str(uuid.uuid7()),
        "playthroughs": [{"id": str(uuid.uuid7()), "playthrough": str(uuid.uuid7())}],
        "duration_seconds": 3600,
        "provenance": "manually_entered",
        "device": None,
        "emulated": True,
        "note": "read off Steam",
        "release": None,
        "source": None,
    }
    columns = columns_for_statement(payload, TemporalValue.parse("2005"))
    assert set(columns) == {
        "player_game_id",
        "duration",
        "when",
        "provenance",
        "device_id",
        "emulated",
        "note",
    }
    assert columns["when"] == "2005"
    assert columns["duration"] == timedelta(hours=1)
    assert columns["provenance"] is HistoricalPlaytimeProvenance.MANUALLY_ENTERED
    assert columns_for_statement(payload, None)["when"] is None


@pytest.mark.django_db(transaction=True)
def test_the_creation_writes_the_record_and_its_runs(
    owned_user, owned_library, tracked, run
):
    second = a_second_run(owned_library, tracked)
    event = a_created(tracked, [run, second])
    append(owned_library, owned_user, event, key="create")

    record = HistoricalPlaytime.objects.get()
    assert record.pk == event.aggregate_id
    assert record.library_id == owned_library.pk
    assert record.player_game_id == tracked.pk
    assert record.when.canonical == "2005"
    assert record.duration == timedelta(hours=100)
    assert record.removed_at is None
    assert set(record.runs.values_list("playthrough_id", flat=True)) == {
        run.pk,
        second.pk,
    }
    assert set(record.runs.values_list("id", flat=True)) == {
        uuid.UUID(member["id"]) for member in event.payload["playthroughs"]
    }
    assert set(record.runs.values_list("library_id", flat=True)) == {owned_library.pk}


@pytest.mark.django_db(transaction=True)
def test_a_restatement_replaces_the_runs_and_keeps_a_kept_id(
    owned_user, owned_library, tracked, run
):
    second = a_second_run(owned_library, tracked)
    created = a_created(tracked, [run, second])
    append(owned_library, owned_user, created, key="create")
    kept = next(
        m for m in created.payload["playthroughs"] if m["playthrough"] == str(run.pk)
    )

    restated = historicalplaytime_restated(
        created.aggregate_id,
        player_game_id=tracked.pk,
        runs=[kept],
        duration=timedelta(hours=50),
        when=TemporalValue.parse("2006~"),
        provenance="manually_entered",
        device=None,
        emulated=True,
        note="halved",
    )
    append(owned_library, owned_user, restated, key="restate")

    record = HistoricalPlaytime.objects.get()
    assert record.duration == timedelta(hours=50)
    assert record.when.canonical == "2006~"
    assert record.provenance == HistoricalPlaytimeProvenance.MANUALLY_ENTERED
    assert record.emulated is True
    assert record.note == "halved"
    assert list(record.runs.values_list("id", "playthrough_id")) == [
        (uuid.UUID(kept["id"]), run.pk)
    ]


@pytest.mark.django_db(transaction=True)
def test_removed_and_restored_move_the_mark(owned_user, owned_library, tracked, run):
    created = a_created(tracked, [run])
    append(owned_library, owned_user, created, key="create")
    append(
        owned_library,
        owned_user,
        historicalplaytime_removed(created.aggregate_id),
        key="remove",
    )
    assert HistoricalPlaytime.objects.get().removed_at is not None
    assert not HistoricalPlaytimeRun.objects.alive().exists()
    append(
        owned_library,
        owned_user,
        historicalplaytime_restored(created.aggregate_id),
        key="restore",
    )
    assert HistoricalPlaytime.objects.get().removed_at is None
    assert HistoricalPlaytimeRun.objects.alive().count() == 1


@pytest.mark.django_db(transaction=True)
def test_the_projection_replays_from_an_empty_stream(
    owned_user, owned_library, tracked, run
):
    created = a_created(tracked, [run])
    append(owned_library, owned_user, created, key="create")
    append(
        owned_library,
        owned_user,
        historicalplaytime_restated(
            created.aggregate_id,
            player_game_id=tracked.pk,
            runs=created.payload["playthroughs"],
            duration=timedelta(hours=2),
            when=TemporalValue.unknown(),
            provenance="estimated",
            device=None,
            emulated=False,
            note="",
        ),
        key="restate",
    )
    before_records = list(HistoricalPlaytime.objects.order_by("pk").values())
    before_runs = list(HistoricalPlaytimeRun.objects.order_by("pk").values())

    HistoricalPlaytimeRun.objects.all().delete()
    HistoricalPlaytime.objects.all().delete()
    replay(owned_library)

    assert list(HistoricalPlaytime.objects.order_by("pk").values()) == before_records
    assert list(HistoricalPlaytimeRun.objects.order_by("pk").values()) == before_runs


@pytest.mark.django_db(transaction=True)
def test_a_rebuild_swaps_both_tables_with_an_empty_diff(
    owned_user, owned_library, game
):
    """A rebuild reproduces a command's run."""
    dispatch(
        TrackGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="track",
    )
    tracked_run = Playthrough.objects.get(player_game__game=game)
    created = a_created(tracked_run.player_game, [tracked_run])
    append(owned_library, owned_user, created, key="create")
    append(
        owned_library,
        owned_user,
        historicalplaytime_removed(created.aggregate_id),
        key="remove",
    )

    report = rebuild_projections(owned_library, mode=RebuildMode.REBUILD)

    assert report.swapped is True
    assert [
        (table.table, table.only_live, table.only_rebuilt, table.differing)
        for table in report.tables
    ] == [
        ("games_device", 0, 0, 0),
        ("games_historicalplaytime", 0, 0, 0),
        ("games_historicalplaytimerun", 0, 0, 0),
        ("games_librarycalendar", 0, 0, 0),
        ("games_playergame", 0, 0, 0),
        ("games_playersession", 0, 0, 0),
        ("games_playthrough", 0, 0, 0),
    ]
    assert HistoricalPlaytimeRun.objects.count() == 1
