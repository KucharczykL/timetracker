"""The projection write guard refuses writes, and its doors hold."""

import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from devices import create_device
from django.db import connection, connections, transaction
from django.db.models import Model
from entries import record_entry
from graphs import default_graph
from projection_doors import (
    _frame_permits_seeding,
    _seed_from_tests,
    classify,
    strict_projection_guard,
)
from purchases import record_purchase, request_run

from games import tasks
from games.commands.calendar import SetCalendarDayZone
from games.commands.historical_playtime import (
    HistoricalPlaytimeStatement,
    RecordHistoricalPlaytime,
)
from games.commands.playersession import CreateSession, DurationOnlyTiming
from games.events.dispatch import Command, append_command
from games.models import (
    Device,
    Game,
    HistoricalPlaytime,
    HistoricalPlaytimeProvenance,
    HistoricalPlaytimeRun,
    LibraryCalendar,
    LibraryEntry,
    PlayerGame,
    PlayerSession,
    Playthrough,
    Purchase,
    PurchaseValuation,
    UserLibrary,
)
from games.projection_writers import (
    ProjectionWriter,
    ProjectionWriteRefused,
    open_writer,
    projection_writes,
    refuse_unpermitted_writes,
)
from games.projections import projection_models
from timetracker.temporal import TemporalValue

GUARDED_MODELS: tuple[type[Model], ...] = (*projection_models(), PurchaseValuation)


def _state(library: UserLibrary, command: Command) -> None:
    """Append one command, the way the test helpers do: no dispatch nesting."""
    with transaction.atomic():
        append_command(
            command,
            actor=library.user,
            library=library,
            idempotency_key=str(uuid.uuid7()),
            correlation_id=uuid.uuid7(),
        )


@pytest.fixture
def seeded_library(owned_library):
    """One populated library: a real row in every guarded table.

    Written through commands and the helpers the suite already uses,
    so the rows are the ones the write path produces.
    """
    library = owned_library
    tunic = Game.objects.create(library=library, name="Tunic")
    hades = Game.objects.create(library=library, name="Hades")
    #: Tracking a game writes its PlayerGame and first Playthrough.
    first_run = Playthrough.objects.get(player_game__game=tunic)
    _state(library, SetCalendarDayZone(day_zone="Europe/Prague"))
    _state(
        library,
        CreateSession(
            playthrough_id=first_run.pk,
            timing=DurationOnlyTiming(
                day=date(2024, 3, 1), duration=timedelta(hours=1)
            ),
            implies_played=False,
        ),
    )
    _state(
        library,
        RecordHistoricalPlaytime(
            statement=HistoricalPlaytimeStatement(
                duration=timedelta(hours=10),
                when="2019",
                provenance=HistoricalPlaytimeProvenance.ESTIMATED,
                playthrough_ids=(first_run.pk,),
                device_id=None,
                release_id=None,
                emulated=False,
                note="Seeded record",
            )
        ),
    )
    create_device(library, "Steam Deck")
    release = default_graph(Game(name="Celeste", library=library), library).release
    entry = record_entry(library, release)
    record_purchase(
        entry,
        amount=Decimal("10.00"),
        currency="CZK",
        purchased=TemporalValue.parse("2021-03-01"),
    )
    #: Same-currency: no rate needed, so the run publishes a valuation.
    tasks.convert_library_prices(str(library.pk), request_run(library, "CZK"))
    assert Playthrough.objects.filter(player_game__game=hades).exists()
    for model in GUARDED_MODELS:
        assert model._base_manager.exists(), f"No seeded row in {model._meta.db_table}"
    return library


#: A column the refused UPDATE changes, and its new value.
CHANGED_COLUMN: dict[type[Model], tuple[str, Callable[[Any], Any]]] = {
    Device: ("name", lambda row: "Renamed device"),
    PlayerGame: ("mastered", lambda row: not row.mastered),
    Playthrough: ("name", lambda row: "Renamed run"),
    PlayerSession: ("note", lambda row: "Changed note"),
    LibraryCalendar: ("day_zone", lambda row: "Pacific/Niue"),
    HistoricalPlaytime: ("note", lambda row: "Changed note"),
    HistoricalPlaytimeRun: ("playthrough_id", lambda row: _other_run(row).pk),
    LibraryEntry: ("note", lambda row: "Changed note"),
    Purchase: ("note", lambda row: "Changed note"),
    PurchaseValuation: ("amount", lambda row: row.amount + Decimal("1.00")),
}


def _other_run(row: HistoricalPlaytimeRun) -> Playthrough:
    """A run the seeded record does not name."""
    other = Playthrough._base_manager.exclude(pk=row.playthrough_id).first()
    assert other is not None, "The seed holds one run only."
    return other


def _seeded_row(model: type[Model]) -> Model:
    row = model._base_manager.order_by("pk").first()
    assert row is not None, f"No seeded row in {model._meta.db_table}"
    return row


def _snapshot(model: type[Model], pk: Any) -> list[dict[str, Any]]:
    """The row as `.values()` answers it; empty when absent."""
    return list(model._base_manager.filter(pk=pk).values())


def noop(execute: Callable[..., Any], sql, params, many, context):
    return execute(sql, params, many, context)


def _pk_name(model: type[Model]) -> str:
    return model._meta.pk.attname


def _table_count(model: type[Model]) -> int:
    return model._base_manager.count()


def _raw(sql: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(sql)


def _in_fresh_connection(action: Callable[[Any], Any]) -> Any:
    """Run `action` on a connection its own thread opens; re-raise its failure."""

    def target() -> Any:
        thread_connection = connections["default"]
        try:
            return action(thread_connection)
        finally:
            thread_connection.close()

    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(target).result()


@pytest.mark.django_db
@pytest.mark.parametrize("model", GUARDED_MODELS, ids=lambda m: m.__name__)
def test_a_guarded_update_is_refused_strictly(model, seeded_library):
    row = _seeded_row(model)
    column, changed = CHANGED_COLUMN[model]
    before_count = _table_count(model)
    before_row = _snapshot(model, row.pk)
    with (
        strict_projection_guard(),
        pytest.raises(ProjectionWriteRefused),
        #: The savepoint keeps the test transaction usable after a refusal.
        transaction.atomic(),
    ):
        model._base_manager.filter(pk=row.pk).update(**{column: changed(row)})
    assert _table_count(model) == before_count
    assert _snapshot(model, row.pk) == before_row


@pytest.mark.django_db
@pytest.mark.parametrize("model", GUARDED_MODELS, ids=lambda m: m.__name__)
def test_a_guarded_bulk_create_is_refused_strictly(model, seeded_library):
    row = _seeded_row(model)
    before_count = _table_count(model)
    before_row = _snapshot(model, row.pk)
    fresh = model(**{_pk_name(model): uuid.uuid7(), "library_id": seeded_library.pk})
    with (
        strict_projection_guard(),
        pytest.raises(ProjectionWriteRefused),
        transaction.atomic(),
    ):
        model._base_manager.bulk_create([fresh])
    assert _table_count(model) == before_count
    assert _snapshot(model, row.pk) == before_row


@pytest.mark.django_db
@pytest.mark.parametrize("model", GUARDED_MODELS, ids=lambda m: m.__name__)
def test_a_guarded_raw_delete_is_refused_strictly(model, seeded_library):
    row = _seeded_row(model)
    before_count = _table_count(model)
    before_row = _snapshot(model, row.pk)
    with (
        strict_projection_guard(),
        pytest.raises(ProjectionWriteRefused),
        transaction.atomic(),
    ):
        _raw(f'DELETE FROM "{model._meta.db_table}"')
    assert _table_count(model) == before_count
    assert _snapshot(model, row.pk) == before_row


@pytest.mark.django_db
def test_a_valuation_door_cannot_write_a_projection(projection_guard_strict):
    projection = next(model for model in projection_models())
    with (
        projection_writes(ProjectionWriter.VALUATION_PUBLISHER),
        pytest.raises(ProjectionWriteRefused),
    ):
        _raw(f'DELETE FROM "{projection._meta.db_table}"')


@pytest.mark.django_db
def test_a_projector_door_cannot_write_the_valuation(projection_guard_strict):
    with (
        projection_writes(ProjectionWriter.PROJECTOR),
        pytest.raises(ProjectionWriteRefused),
    ):
        _raw(f'DELETE FROM "{PurchaseValuation._meta.db_table}"')


@pytest.mark.django_db
def test_a_permitted_door_runs_its_write(projection_guard_strict):
    projection = next(model for model in projection_models())
    with projection_writes(ProjectionWriter.PROJECTOR):
        _raw(f'DELETE FROM "{projection._meta.db_table}" WHERE false')


@pytest.mark.django_db
def test_a_test_frame_seeds_without_strict():
    projection = next(model for model in projection_models())
    _raw(f'DELETE FROM "{projection._meta.db_table}" WHERE false')


@pytest.mark.parametrize(
    ("parts", "expected"),
    [
        (("tests", "x.py"), "test"),
        (("e2e", "x.py"), "test"),
        (("games", "x.py"), "app"),
        (("common", "x.py"), "app"),
        (("timetracker", "x.py"), "app"),
        (("contrib", "x.py"), "app"),
        (("scripts", "x.py"), "app"),
        ((".venv", "lib"), None),
        ((), None),
    ],
)
def test_classify_names_the_source_tree(parts, expected):
    assert classify(parts) == expected


def test_the_seeding_frame_check_permits_a_test_file():
    assert _frame_permits_seeding() is True


@pytest.mark.django_db(transaction=True)
def test_the_guard_survives_a_connection_opened_inside_a_wrapper():
    def action(thread_connection):
        with thread_connection.execute_wrapper(noop):
            thread_connection.ensure_connection()
        return list(thread_connection.execute_wrappers)

    wrappers = _in_fresh_connection(action)
    assert refuse_unpermitted_writes in wrappers
    assert noop not in wrappers


@pytest.mark.django_db(transaction=True)
def test_a_reconnect_does_not_duplicate_the_guard():
    def action(thread_connection):
        thread_connection.ensure_connection()
        thread_connection.close()
        thread_connection.ensure_connection()
        return list(thread_connection.execute_wrappers)

    wrappers = _in_fresh_connection(action)
    assert wrappers.count(refuse_unpermitted_writes) == 1
    assert wrappers.count(_seed_from_tests) == 1
    seed_index = wrappers.index(_seed_from_tests)
    assert wrappers[seed_index + 1] is refuse_unpermitted_writes


def test_the_migrate_door_opens_on_pre_migrate_and_closes_on_post_migrate():
    from games import apps

    assert open_writer() is None
    try:
        apps._open_migrate_door(sender=None)
        assert open_writer() is ProjectionWriter.MIGRATE
        apps._close_migrate_door(sender=None)
        assert open_writer() is None
    finally:
        apps._close_migrate_door(sender=None)
    apps._close_migrate_door(sender=None)
    assert open_writer() is None
