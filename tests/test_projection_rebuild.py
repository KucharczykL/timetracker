"""Rebuilding one library's projections through shadow tables."""

from collections.abc import Callable
from dataclasses import replace
from io import StringIO
from random import Random
from typing import Any, ClassVar, TypedDict
from uuid import UUID, uuid4, uuid7

import pytest
from django.core.checks import run_checks
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, transaction
from django.test.utils import isolate_apps
from pydantic import ConfigDict, with_config
from test_projection_targets import ENTRY_TABLE, SHELF_TABLE, declare_projection_models
from test_uuid_identity_audit import EXPECTED_RELATION_COLUMNS

from games.events import rebuild as rebuild_module
from games.events.append import StreamSequenceMismatch, lock_stream
from games.events.envelope import RecordedEvent
from games.events.projection import (
    HandlerMap,
    Projector,
    ProjectorFamily,
    ProjectorRegistry,
)
from games.events.rebuild import (
    DIFF_SAMPLE_LIMIT,
    LiveWriteRefused,
    RebuildAttempt,
    RebuildMode,
    RebuildReport,
    TableDiff,
    diff_table,
    diff_tables,
    insertable_columns,
    only_shadow_writes,
    projection_models,
    rebuild_projections,
    replay_into_shadow,
    shadow_tables,
    swap_in,
    write_targets,
)
from games.events.replay import ReplayResult, StreamNotContiguous
from games.events.retry import RetryPolicy
from games.events.targets import SHADOW_SUFFIX, ShadowTarget
from games.events.vocabulary import EventSpec, EventTypeRegistry, NewEvent
from games.events.wiring import EventWiring
from games.identity_audit import relation_columns
from games.management.commands import rebuild_projections as rebuild_command
from games.models import (
    LibraryEvent,
    LibraryEventStreamHead,
    PlayerGame,
    ProjectionModel,
    UserLibrary,
)


def create_tables(*models: type[ProjectionModel]) -> None:
    """The tables, rolled back with the test."""
    with connection.schema_editor() as schema_editor:
        for model in models:
            schema_editor.create_model(model)


def shadow_of(table: str) -> str:
    return f'pg_temp."{table}{SHADOW_SUFFIX}"'


def relation_exists(relation: str) -> bool:
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass(%s) IS NOT NULL", [relation])
        return bool(cursor.fetchone()[0])


def index_count(relation: str) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM pg_index WHERE indrelid = to_regclass(%s)",
            [relation],
        )
        return int(cursor.fetchone()[0])


def foreign_key_count(relation: str) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT count(*) FROM pg_constraint
            WHERE conrelid = to_regclass(%s) AND contype = 'f'
            """,
            [relation],
        )
        return int(cursor.fetchone()[0])


def table_columns(relation: str) -> list[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT attname FROM pg_attribute
            WHERE attrelid = to_regclass(%s) AND attnum > 0 AND NOT attisdropped
            ORDER BY attnum
            """,
            [relation],
        )
        return [name for (name,) in cursor.fetchall()]


@pytest.mark.django_db
@isolate_apps("games")
def test_discovery_finds_the_projection_tables_in_the_given_registry():
    shelf, entry = declare_projection_models()

    assert set(projection_models(shelf._meta.apps)) == {shelf, entry}


@pytest.mark.django_db
@isolate_apps("games")
def test_discovery_passes_over_a_manufactured_twin():
    shelf, entry = declare_projection_models()
    ShadowTarget().model(shelf)

    #: Only `managed = False` excludes a twin.
    assert set(projection_models(shelf._meta.apps)) == {shelf, entry}


def test_the_application_declares_the_playergame_projection():
    """The one projection table so far."""
    assert projection_models() == (PlayerGame,)


@pytest.mark.django_db
@isolate_apps("games")
def test_a_shadow_table_exists_for_the_length_of_the_block():
    shelf, entry = declare_projection_models()
    create_tables(shelf, entry)

    with shadow_tables([shelf, entry]):
        assert relation_exists(shadow_of(SHELF_TABLE))
        assert relation_exists(shadow_of(ENTRY_TABLE))

    assert not relation_exists(shadow_of(SHELF_TABLE))
    assert not relation_exists(shadow_of(ENTRY_TABLE))


@pytest.mark.django_db
@isolate_apps("games")
def test_a_shadow_table_is_dropped_when_the_block_raises():
    shelf, _ = declare_projection_models()
    create_tables(shelf)

    with (
        pytest.raises(RuntimeError, match="the family refused"),
        shadow_tables([shelf]),
    ):
        raise RuntimeError("the family refused")

    assert not relation_exists(shadow_of(SHELF_TABLE))


@pytest.mark.django_db
@isolate_apps("games")
def test_a_shadow_table_carries_the_live_columns_and_indexes():
    shelf, _ = declare_projection_models()
    create_tables(shelf)

    with shadow_tables([shelf]):
        assert table_columns(shadow_of(SHELF_TABLE)) == table_columns(
            f'"{SHELF_TABLE}"'
        )
        #: A family reads back its own writes.
        assert index_count(shadow_of(SHELF_TABLE)) == index_count(f'"{SHELF_TABLE}"')
        assert index_count(shadow_of(SHELF_TABLE)) > 1


@pytest.mark.django_db
@isolate_apps("games")
def test_a_shadow_table_carries_no_foreign_key():
    shelf, entry = declare_projection_models()
    create_tables(shelf, entry)

    with shadow_tables([shelf, entry]):
        #: No foreign keys: any fill order works.
        assert foreign_key_count(f'"{ENTRY_TABLE}"') == 2
        assert foreign_key_count(shadow_of(ENTRY_TABLE)) == 0


@pytest.mark.django_db
@isolate_apps("games")
def test_the_insertable_columns_are_the_tables_own_minus_the_generated_one():
    shelf, _ = declare_projection_models()
    create_tables(shelf)

    columns = table_columns(f'"{SHELF_TABLE}"')

    assert "played_minutes" in columns
    #: PostgreSQL refuses a generated column.
    assert insertable_columns(shelf) == tuple(
        column for column in columns if column != "played_minutes"
    )


# --- The write guard --------------------------------------------------------
#
# One test per path a signal misses.

type WritePath = Callable[[type[ProjectionModel], UserLibrary], None]


def seed_shelf(model, library, **overrides):
    """One row in the given shelf table."""
    fields = {
        "id": uuid4(),
        "library_id": library.pk,
        "title": "seeded",
        "played_seconds": 60,
    }
    fields.update(overrides)
    return model.objects.create(**fields)


def save_one(model, library):
    model(id=uuid4(), library_id=library.pk, title="saved").save()


def create_one(model, library):
    model.objects.create(id=uuid4(), library_id=library.pk, title="created")


def bulk_create_one(model, library):
    model.objects.bulk_create(
        [model(id=uuid4(), library_id=library.pk, title="bulk-created")]
    )


def update_every_row(model, library):
    model.objects.filter(library_id=library.pk).update(title="updated")


def bulk_update_one(model, library):
    row = model.objects.filter(library_id=library.pk).first()
    row.title = "bulk-updated"
    model.objects.bulk_update([row], ["title"])


def delete_every_row(model, library):
    model.objects.filter(library_id=library.pk).delete()


def insert_through_a_raw_cursor(model, library):
    with connection.cursor() as cursor:
        cursor.execute(
            f'INSERT INTO "{model._meta.db_table}" '
            '("id", "library_id", "title", "played_seconds") VALUES (%s, %s, %s, %s)',
            [uuid4(), library.pk, "raw", 0],
        )


WRITE_PATHS: list[WritePath] = [
    save_one,
    create_one,
    bulk_create_one,
    update_every_row,
    bulk_update_one,
    delete_every_row,
    insert_through_a_raw_cursor,
]
WRITE_PATH_NAMES = [path.__name__ for path in WRITE_PATHS]


@pytest.mark.parametrize("write", WRITE_PATHS, ids=WRITE_PATH_NAMES)
@pytest.mark.django_db
@isolate_apps("games")
def test_the_guard_refuses_a_write_to_a_live_projection_table(write, owned_library):
    shelf, entry = declare_projection_models()
    create_tables(shelf, entry)
    seed_shelf(shelf, owned_library)

    #: A cascade reaches the child table first.
    with only_shadow_writes(), pytest.raises(LiveWriteRefused, match="not a shadow"):
        write(shelf, owned_library)


@pytest.mark.parametrize("write", WRITE_PATHS, ids=WRITE_PATH_NAMES)
@pytest.mark.django_db
@isolate_apps("games")
def test_a_write_path_works_again_once_the_block_exits(write, owned_library):
    shelf, entry = declare_projection_models()
    create_tables(shelf, entry)
    seed_shelf(shelf, owned_library)

    #: A savepoint contains the marked rollback.
    with only_shadow_writes(), pytest.raises(LiveWriteRefused), transaction.atomic():
        write(shelf, owned_library)

    #: The guard is phase-local.
    write(shelf, owned_library)


@pytest.mark.django_db
@isolate_apps("games")
def test_the_refusal_names_the_table_and_quotes_the_statement(owned_library):
    shelf, entry = declare_projection_models()
    create_tables(shelf, entry)

    with only_shadow_writes(), pytest.raises(LiveWriteRefused) as refusal:
        create_one(shelf, owned_library)

    message = str(refusal.value)
    assert SHELF_TABLE in message
    assert "INSERT" in message


@pytest.mark.django_db
@isolate_apps("games")
def test_a_write_to_a_shadow_table_is_allowed(owned_library):
    shelf, entry = declare_projection_models()
    create_tables(shelf, entry)
    twin = ShadowTarget().model(shelf)

    with shadow_tables([shelf]), only_shadow_writes():
        twin.objects.create(id=uuid4(), library_id=owned_library.pk, title="projected")
        assert twin.objects.count() == 1

    assert shelf.objects.count() == 0


@pytest.mark.django_db
@isolate_apps("games")
def test_a_read_of_a_live_table_is_allowed(owned_library):
    shelf, entry = declare_projection_models()
    create_tables(shelf, entry)
    seed_shelf(shelf, owned_library)

    with only_shadow_writes():
        #: Only writes are refused.
        assert shelf.objects.count() == 1


@pytest.mark.django_db
def test_the_guard_refuses_a_write_to_a_table_no_rebuild_touches(owned_library):
    """An allowlist, not the rebuilt tables."""
    with only_shadow_writes(), pytest.raises(LiveWriteRefused, match="userlibrary"):
        UserLibrary.objects.filter(pk=owned_library.pk).update(
            created_at=owned_library.created_at
        )


def insert_into(relation: str) -> str:
    return (
        f"INSERT INTO {relation} "
        '("id", "library_id", "title", "played_seconds") VALUES (%s, %s, %s, %s)'
    )


#: Each prefix moves the write past the first keyword.
HIDING_PREFIXES = ["WITH counted AS (SELECT 1) ", "/* a comment */ ", "-- a comment\n"]


@pytest.mark.parametrize(
    "prefix", HIDING_PREFIXES, ids=["cte", "block_comment", "line_comment"]
)
@pytest.mark.django_db
@isolate_apps("games")
def test_the_guard_refuses_a_live_write_the_first_keyword_hides(prefix, owned_library):
    shelf, entry = declare_projection_models()
    create_tables(shelf, entry)

    with (
        only_shadow_writes(),
        pytest.raises(LiveWriteRefused, match="not a shadow"),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            prefix + insert_into(f'"{SHELF_TABLE}"'),
            [uuid4(), owned_library.pk, "hidden", 0],
        )


@pytest.mark.parametrize(
    ("statement", "expected"),
    [
        ('INSERT INTO "games_playergame" (id) VALUES (%s)', ("games_playergame",)),
        (
            '/* a comment */ INSERT INTO "games_playergame" (id) VALUES (%s)',
            ("games_playergame",),
        ),
        (
            (
                'WITH moved AS (DELETE FROM "old" RETURNING *) '
                'INSERT INTO "new" SELECT * FROM moved'
            ),
            ("old", "new"),
        ),
        ('SELECT 1 FROM "games_playergame"', ()),
        ("SAVEPOINT s1", ()),
        (
            'UPDATE ONLY pg_temp."games_playergame__shadow" SET id = id',
            ("games_playergame__shadow",),
        ),
    ],
)
def test_write_targets_names_every_table_a_statement_writes(statement, expected):
    assert write_targets(statement) == expected


def test_write_targets_refuses_a_write_it_cannot_parse():
    #: An empty name is a refusal, not a miss.
    assert write_targets("INSERT INTO (broken") == ("",)


@pytest.mark.django_db
@isolate_apps("games")
def test_a_read_only_cte_is_allowed(owned_library):
    shelf, entry = declare_projection_models()
    create_tables(shelf, entry)
    seed_shelf(shelf, owned_library)

    with only_shadow_writes(), connection.cursor() as cursor:
        cursor.execute(
            f'WITH counted AS (SELECT count(*) AS total FROM "{SHELF_TABLE}") '
            "SELECT total FROM counted"
        )
        assert cursor.fetchone() == (1,)


@pytest.mark.django_db
@isolate_apps("games")
def test_a_cte_writing_a_shadow_table_is_allowed(owned_library):
    shelf, entry = declare_projection_models()
    create_tables(shelf, entry)

    with shadow_tables([shelf]), only_shadow_writes(), connection.cursor() as cursor:
        cursor.execute(
            "WITH counted AS (SELECT 1) " + insert_into(shadow_of(SHELF_TABLE)),
            [uuid4(), owned_library.pk, "projected", 0],
        )

    assert shelf.objects.count() == 0


@pytest.mark.django_db
@isolate_apps("games")
def test_a_shadow_write_that_ends_in_a_semicolon_is_allowed():
    """The identifier keeps its quote if the order is wrong."""
    shelf, entry = declare_projection_models()
    create_tables(shelf, entry)

    with shadow_tables([shelf]), only_shadow_writes(), connection.cursor() as cursor:
        #: The table is the last token, so the semicolon rides on it.
        cursor.execute(f"DELETE FROM {shadow_of(SHELF_TABLE)};")


@pytest.mark.django_db
@isolate_apps("games")
def test_a_shadow_write_naming_only_is_allowed():
    """`ONLY` is a keyword, not the table."""
    shelf, entry = declare_projection_models()
    create_tables(shelf, entry)

    with shadow_tables([shelf]), only_shadow_writes(), connection.cursor() as cursor:
        cursor.execute(f'UPDATE ONLY {shadow_of(SHELF_TABLE)} SET "title" = %s', ["x"])


# --- Phase 2: the replay ----------------------------------------------------
#
# Registries this module owns, never `DEFAULT_REGISTRY`.


@with_config(ConfigDict(extra="forbid", strict=True))
class ShelfPayload(TypedDict):
    title: str


PROBE_SHELVED = EventSpec(
    "library.probe.shelved", aggregate_type="probe", payload=ShelfPayload
)
EVENT_TYPES = EventTypeRegistry()
EVENT_TYPES.register(PROBE_SHELVED)

#: Set per test, read by the family.
DECLARED_SHELF: list[type[ProjectionModel]] = []


def declared_shelf() -> Any:
    """The shelf model the running test declared."""
    return DECLARED_SHELF[-1]


shadow_registry = ProjectorRegistry()
live_writing_registry = ProjectorRegistry()


class Shelver(Projector, registry=shadow_registry):
    """A family that writes its target."""

    family_name = ProjectorFamily.CURRENT_STATE

    def _shelved(self, event: RecordedEvent) -> None:
        projected = self.target.model(declared_shelf())
        projected.objects.create(
            id=event.aggregate_id,
            library_id=event.library_id,
            title=event.payload["title"],
        )

    handles: ClassVar[HandlerMap] = {PROBE_SHELVED: _shelved}


class StubbornShelver(Projector, registry=live_writing_registry):
    """A family that writes its live model."""

    family_name = ProjectorFamily.CURRENT_STATE

    def _shelved(self, event: RecordedEvent) -> None:
        declared_shelf().objects.create(
            id=event.aggregate_id,
            library_id=event.library_id,
            title=event.payload["title"],
        )

    handles: ClassVar[HandlerMap] = {PROBE_SHELVED: _shelved}


SHADOW_WIRING = EventWiring(projectors=shadow_registry, event_types=EVENT_TYPES)
LIVE_WRITING_WIRING = EventWiring(
    projectors=live_writing_registry, event_types=EVENT_TYPES
)


@pytest.fixture(autouse=True)
def forget_the_declared_model():
    yield
    DECLARED_SHELF.clear()


def declare_and_create_shelf() -> type[ProjectionModel]:
    shelf, entry = declare_projection_models()
    create_tables(shelf, entry)
    DECLARED_SHELF.append(shelf)
    return shelf


def append_shelved(library, titles, *, wiring=SHADOW_WIRING):
    """One append, one event per title."""
    events = [
        NewEvent(spec=PROBE_SHELVED, aggregate_id=uuid7(), payload={"title": title})
        for title in titles
    ]
    with transaction.atomic():
        return lock_stream(library).append(
            events,
            actor=None,
            correlation_id=uuid7(),
            idempotency_key=f"probe-{uuid7()}",
            wiring=wiring,
        )


def shelf_rows(model) -> list[tuple[UUID, str]]:
    return sorted(model.objects.values_list("id", "title"))


def head_sequence(library) -> int:
    return LibraryEventStreamHead.objects.get(library=library).current_sequence


@pytest.mark.django_db
@isolate_apps("games")
def test_the_replay_fills_the_shadow_and_leaves_the_live_rows_alone(owned_library):
    shelf = declare_and_create_shelf()
    append_shelved(owned_library, ["one", "two", "three"])
    live_rows = shelf_rows(shelf)
    twin = ShadowTarget().model(shelf)

    with shadow_tables([shelf]):
        result = replay_into_shadow(owned_library, [shelf], wiring=SHADOW_WIRING)

        #: The parity the whole issue is about.
        assert shelf_rows(twin) == live_rows

    assert shelf_rows(shelf) == live_rows
    assert result.replayed_through == head_sequence(owned_library)


@pytest.mark.django_db
@isolate_apps("games")
def test_a_family_writing_its_live_model_is_refused(owned_library):
    shelf = declare_and_create_shelf()
    append_shelved(owned_library, ["one"], wiring=LIVE_WRITING_WIRING)
    live_rows = shelf_rows(shelf)

    with shadow_tables([shelf]), pytest.raises(LiveWriteRefused):
        replay_into_shadow(owned_library, [shelf], wiring=LIVE_WRITING_WIRING)

    assert shelf_rows(shelf) == live_rows


@pytest.mark.django_db
@isolate_apps("games")
def test_a_hole_in_the_stream_refuses_the_replay_as_itself(owned_library):
    """`StreamNotContiguous` arrives with its own type."""
    shelf = declare_and_create_shelf()
    append_shelved(owned_library, ["one", "two", "three"])
    LibraryEvent.objects.filter(library=owned_library, sequence=2).delete()

    with shadow_tables([shelf]), pytest.raises(StreamNotContiguous, match="2"):
        replay_into_shadow(owned_library, [shelf], wiring=SHADOW_WIRING)


@pytest.mark.django_db
@isolate_apps("games")
def test_a_library_that_never_appended_replays_nothing(owned_library):
    shelf = declare_and_create_shelf()
    twin = ShadowTarget().model(shelf)

    with shadow_tables([shelf]):
        result = replay_into_shadow(owned_library, [shelf], wiring=SHADOW_WIRING)

        assert shelf_rows(twin) == []

    assert result == ReplayResult(stream_id=None, replayed_through=0)


@pytest.mark.django_db
@isolate_apps("games")
def test_the_replay_refuses_to_run_without_its_shadow_tables(owned_library):
    """The phase names the missing tables."""
    shelf = declare_and_create_shelf()
    append_shelved(owned_library, ["one"])

    with pytest.raises(RuntimeError, match=f"{SHELF_TABLE}{SHADOW_SUFFIX}"):
        replay_into_shadow(owned_library, [shelf], wiring=SHADOW_WIRING)


# --- Phase 3: the diff ------------------------------------------------------


@pytest.fixture
def second_library(django_user_model):
    return django_user_model.objects.create_user(
        username="second-owner", password="p"
    ).library


def no_difference(table=SHELF_TABLE, *, rows=1) -> TableDiff:
    return TableDiff(
        table=table,
        live_rows=rows,
        rebuilt_rows=rows,
        only_live=0,
        only_rebuilt=0,
        differing=0,
        sample=(),
    )


@pytest.mark.django_db
@isolate_apps("games")
def test_a_shadow_holding_the_same_rows_reports_no_difference(owned_library):
    shelf, _ = declare_projection_models()
    create_tables(shelf)
    twin = ShadowTarget().model(shelf)
    live = seed_shelf(shelf, owned_library, note="kept")

    with shadow_tables([shelf]):
        seed_shelf(twin, owned_library, id=live.id, note="kept")

        #: The generated column agrees by construction.
        assert diff_table(shelf, owned_library) == no_difference()


@pytest.mark.django_db
@isolate_apps("games")
def test_a_row_the_rebuild_did_not_produce_is_only_live(owned_library):
    shelf, _ = declare_projection_models()
    create_tables(shelf)
    live = seed_shelf(shelf, owned_library)

    with shadow_tables([shelf]):
        difference = diff_table(shelf, owned_library)

    assert difference.live_rows == 1
    assert difference.rebuilt_rows == 0
    assert difference.only_live == 1
    assert difference.only_rebuilt == 0
    assert difference.differing == 0
    assert difference.sample == (str(live.id),)


@pytest.mark.django_db
@isolate_apps("games")
def test_a_row_the_live_table_lost_is_only_rebuilt(owned_library):
    shelf, _ = declare_projection_models()
    create_tables(shelf)
    twin = ShadowTarget().model(shelf)

    with shadow_tables([shelf]):
        rebuilt = seed_shelf(twin, owned_library)
        difference = diff_table(shelf, owned_library)

    assert difference.live_rows == 0
    assert difference.rebuilt_rows == 1
    assert difference.only_live == 0
    #: A `WHERE` scope would hide this row.
    assert difference.only_rebuilt == 1
    assert difference.sample == (str(rebuilt.id),)


@pytest.mark.django_db
@isolate_apps("games")
def test_a_column_that_drifted_is_a_differing_row(owned_library):
    shelf, _ = declare_projection_models()
    create_tables(shelf)
    twin = ShadowTarget().model(shelf)
    live = seed_shelf(shelf, owned_library, played_seconds=60)

    with shadow_tables([shelf]):
        seed_shelf(twin, owned_library, id=live.id, played_seconds=120)
        difference = diff_table(shelf, owned_library)

    assert difference.differing == 1
    assert difference.only_live == 0
    assert difference.only_rebuilt == 0
    assert difference.sample == (str(live.id),)


@pytest.mark.parametrize(
    ("live_note", "rebuilt_note"),
    [("kept", None), (None, "kept")],
    ids=["null-in-the-rebuild", "null-in-the-live-row"],
)
@pytest.mark.django_db
@isolate_apps("games")
def test_a_column_that_drifted_to_or_from_null_is_a_differing_row(
    live_note, rebuilt_note, owned_library
):
    """The null-safety pin."""
    shelf, _ = declare_projection_models()
    create_tables(shelf)
    twin = ShadowTarget().model(shelf)
    live = seed_shelf(shelf, owned_library, note=live_note)

    with shadow_tables([shelf]):
        seed_shelf(twin, owned_library, id=live.id, note=rebuilt_note)
        difference = diff_table(shelf, owned_library)

    assert difference.differing == 1
    assert difference.sample == (str(live.id),)


@pytest.mark.django_db
@isolate_apps("games")
def test_another_librarys_live_rows_are_not_this_librarys_difference(
    owned_library, second_library
):
    shelf, _ = declare_projection_models()
    create_tables(shelf)
    twin = ShadowTarget().model(shelf)
    live = seed_shelf(shelf, owned_library)
    seed_shelf(shelf, second_library)

    with shadow_tables([shelf]):
        seed_shelf(twin, owned_library, id=live.id)

        assert diff_table(shelf, owned_library) == no_difference()


@pytest.mark.django_db
@isolate_apps("games")
def test_a_wholly_drifted_table_reports_a_bounded_sample(owned_library):
    shelf, _ = declare_projection_models()
    create_tables(shelf)
    drifted = 50
    for index in range(drifted):
        seed_shelf(shelf, owned_library, title=f"live-{index}")

    with shadow_tables([shelf]):
        difference = diff_table(shelf, owned_library)

    assert difference.only_live == drifted
    #: Bounded, so the report stays readable.
    assert len(difference.sample) == DIFF_SAMPLE_LIMIT


@pytest.mark.django_db
@isolate_apps("games")
def test_every_table_is_diffed_in_the_order_it_was_given(owned_library):
    shelf, entry = declare_projection_models()
    create_tables(shelf, entry)

    with shadow_tables([shelf, entry]):
        differences = diff_tables([shelf, entry], owned_library)

    assert differences == (
        no_difference(SHELF_TABLE, rows=0),
        no_difference(ENTRY_TABLE, rows=0),
    )


# --- Phase 4: the swap ------------------------------------------------------

#: One `DELETE` and one `INSERT` per table.
SWAP_STATEMENTS_PER_TABLE = 2
#: The lock, the head read, two savepoints.
SWAP_FIXED_STATEMENTS = 4


def every_column(model, library) -> list[tuple[Any, ...]]:
    """Every column, so "unchanged" is literal."""
    columns = [field.name for field in model._meta.concrete_fields]
    return sorted(model.objects.filter(library_id=library.pk).values_list(*columns))


@pytest.mark.django_db
@isolate_apps("games")
def test_the_swap_replaces_the_live_rows_with_the_rebuilt_ones(owned_library):
    """Drift, loss and a stray row, together."""
    shelf = declare_and_create_shelf()
    append_shelved(owned_library, ["one", "two", "three"])
    correct = shelf_rows(shelf)
    shelf.objects.filter(title="one").update(title="drifted")
    shelf.objects.filter(title="two").delete()
    stray = seed_shelf(shelf, owned_library, title="never-appended")

    with shadow_tables([shelf]):
        replayed = replay_into_shadow(owned_library, [shelf], wiring=SHADOW_WIRING)
        swap_in(owned_library, [shelf], replayed.replayed_through)

    assert shelf_rows(shelf) == correct
    assert not shelf.objects.filter(pk=stray.pk).exists()


@pytest.mark.django_db
@isolate_apps("games")
def test_another_librarys_rows_come_through_the_swap_untouched(
    owned_library, second_library
):
    shelf = declare_and_create_shelf()
    append_shelved(owned_library, ["one"])
    append_shelved(second_library, ["theirs"])
    theirs = every_column(shelf, second_library)

    with shadow_tables([shelf]):
        replayed = replay_into_shadow(owned_library, [shelf], wiring=SHADOW_WIRING)
        swap_in(owned_library, [shelf], replayed.replayed_through)

    #: Every column: a wide scope loses rows.
    assert every_column(shelf, second_library) == theirs


@pytest.mark.django_db
@isolate_apps("games")
def test_a_foreign_row_in_the_shadow_is_left_behind(owned_library, second_library):
    """The swap carries what the lock covers."""
    shelf = declare_and_create_shelf()
    append_shelved(owned_library, ["one"])
    twin = ShadowTarget().model(shelf)

    with shadow_tables([shelf]):
        replayed = replay_into_shadow(owned_library, [shelf], wiring=SHADOW_WIRING)
        #: A family reaching past its library writes one of these.
        twin.objects.create(
            id=uuid4(), library_id=second_library.pk, title="not mine", played_seconds=0
        )
        swap_in(owned_library, [shelf], replayed.replayed_through)

    assert not shelf.objects.filter(library_id=second_library.pk).exists()
    assert [title for _, title in shelf_rows(shelf)] == ["one"]


@pytest.mark.django_db
@isolate_apps("games")
def test_an_event_that_landed_during_the_rebuild_refuses_the_swap(owned_library):
    """The expectation is asserted before any write."""
    shelf = declare_and_create_shelf()
    append_shelved(owned_library, ["one"])

    with shadow_tables([shelf]):
        replayed = replay_into_shadow(owned_library, [shelf], wiring=SHADOW_WIRING)
        append_shelved(owned_library, ["landed-late"])
        live_rows = shelf_rows(shelf)

        with pytest.raises(StreamSequenceMismatch) as conflict:
            swap_in(owned_library, [shelf], replayed.replayed_through)

    assert conflict.value.expected == replayed.replayed_through
    assert conflict.value.actual == head_sequence(owned_library)
    assert shelf_rows(shelf) == live_rows


@pytest.mark.django_db
@isolate_apps("games")
def test_a_library_that_never_appended_is_swapped_empty(owned_library):
    """An empty stream projects to no rows."""
    shelf = declare_and_create_shelf()
    seed_shelf(shelf, owned_library, title="left-over")

    with shadow_tables([shelf]):
        replayed = replay_into_shadow(owned_library, [shelf], wiring=SHADOW_WIRING)
        swap_in(owned_library, [shelf], replayed.replayed_through)

    assert shelf_rows(shelf) == []
    assert head_sequence(owned_library) == 0


@pytest.mark.django_db
@isolate_apps("games")
def test_the_swap_empties_and_refills_every_table_it_is_given(owned_library):
    shelf, entry = declare_projection_models()
    create_tables(shelf, entry)
    DECLARED_SHELF.append(shelf)
    append_shelved(owned_library, ["one"])
    shelved = shelf.objects.get()
    entry.objects.create(
        id=uuid4(), library_id=owned_library.pk, shelf=shelved, position=1
    )

    with shadow_tables([shelf, entry]):
        replayed = replay_into_shadow(
            owned_library, [shelf, entry], wiring=SHADOW_WIRING
        )
        swap_in(owned_library, [shelf, entry], replayed.replayed_through)

    #: A given table is replaced, not extended.
    assert entry.objects.count() == 0
    assert shelf.objects.count() == 1


@pytest.mark.parametrize("rows", [1, 25])
@pytest.mark.django_db
@isolate_apps("games")
def test_the_swap_costs_the_same_statements_at_any_size(
    owned_library, django_assert_num_queries, rows
):
    shelf = declare_and_create_shelf()
    append_shelved(owned_library, [f"title-{index}" for index in range(rows)])

    with shadow_tables([shelf]):
        replayed = replay_into_shadow(owned_library, [shelf], wiring=SHADOW_WIRING)

        with django_assert_num_queries(
            SWAP_FIXED_STATEMENTS + SWAP_STATEMENTS_PER_TABLE
        ):
            swap_in(owned_library, [shelf], replayed.replayed_through)


# --- The attempt loop and the report ----------------------------------------


def recording_policy(**overrides) -> tuple[RetryPolicy, list[float]]:
    """A policy that records its delays."""
    delays: list[float] = []
    return RetryPolicy(sleep=delays.append, random=Random(0), **overrides), delays


class AppendsFirst:
    """Appends just before the wrapped call runs."""

    def __init__(self, wrapped, library, *, appends=None):
        self.wrapped = wrapped
        self.library = library
        #: None means every call.
        self.appends = appends
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        if self.appends is None or self.calls <= self.appends:
            append_shelved(self.library, [f"landed-{self.calls}"])
        return self.wrapped(*args, **kwargs)


def shelf_diff(report) -> TableDiff:
    return next(table for table in report.tables if table.table == SHELF_TABLE)


@pytest.mark.django_db
@isolate_apps("games")
def test_an_append_between_the_replay_and_the_swap_redoes_the_attempt(
    owned_library, monkeypatch
):
    """A stale expectation redoes the whole attempt."""
    shelf = declare_and_create_shelf()
    append_shelved(owned_library, ["one"])
    policy, delays = recording_policy()
    monkeypatch.setattr(
        rebuild_module, "swap_in", AppendsFirst(swap_in, owned_library, appends=1)
    )

    report = rebuild_projections(
        owned_library,
        mode=RebuildMode.REBUILD,
        wiring=replace(SHADOW_WIRING, retry_policy=policy),
        apps=shelf._meta.apps,
    )

    assert report.swapped is True
    assert len(report.attempts) == 2
    assert report.attempts[0].conflict is not None
    assert report.attempts[0].swap_seconds is None
    assert report.attempts[1].conflict is None
    assert report.attempts[1].swap_seconds is not None
    assert report.replayed_through == head_sequence(owned_library) == 2
    assert len(delays) == 1
    assert 0 <= delays[0] <= policy.base_delay
    assert shelf_diff(report).differing == 0


@pytest.mark.django_db
@isolate_apps("games")
def test_a_stream_that_keeps_moving_exhausts_the_budget(owned_library, monkeypatch):
    shelf = declare_and_create_shelf()
    append_shelved(owned_library, ["one"])
    shelf.objects.filter(title="one").update(title="drifted")
    policy, delays = recording_policy(retries=2)
    monkeypatch.setattr(rebuild_module, "swap_in", AppendsFirst(swap_in, owned_library))

    report = rebuild_projections(
        owned_library,
        mode=RebuildMode.REBUILD,
        wiring=replace(SHADOW_WIRING, retry_policy=policy),
        apps=shelf._meta.apps,
    )

    assert report.swapped is False
    assert len(report.attempts) == policy.retries + 1
    assert all(attempt.conflict for attempt in report.attempts)
    #: One sleep between attempts, none after.
    assert len(delays) == policy.retries
    #: The drift a swap would have fixed.
    assert shelf.objects.filter(title="drifted").exists()
    assert not relation_exists(shadow_of(SHELF_TABLE))


@pytest.mark.django_db
@isolate_apps("games")
def test_check_mode_reports_the_drift_and_writes_nothing(owned_library):
    shelf = declare_and_create_shelf()
    append_shelved(owned_library, ["one"])
    shelf.objects.filter(title="one").update(title="drifted")

    report = rebuild_projections(
        owned_library, wiring=SHADOW_WIRING, apps=shelf._meta.apps
    )

    assert report.mode is RebuildMode.CHECK
    assert report.swapped is False
    assert report.library_id == owned_library.pk
    assert report.stream_id is not None
    #: Every projection table, not the projected ones.
    assert [table.table for table in report.tables] == [ENTRY_TABLE, SHELF_TABLE]
    assert shelf_diff(report).differing == 1
    assert report.attempts[0].swap_seconds is None
    #: Nothing written, nothing left behind.
    assert shelf.objects.get().title == "drifted"
    assert not relation_exists(shadow_of(SHELF_TABLE))


@pytest.mark.django_db
@isolate_apps("games")
def test_check_mode_reports_the_head_it_diffed_against(owned_library, monkeypatch):
    """An append during the diff is advisory."""
    shelf = declare_and_create_shelf()
    append_shelved(owned_library, ["one"])
    monkeypatch.setattr(
        rebuild_module, "diff_tables", AppendsFirst(diff_tables, owned_library)
    )

    report = rebuild_projections(
        owned_library, wiring=SHADOW_WIRING, apps=shelf._meta.apps
    )

    assert report.replayed_through == 1
    assert report.head_at_diff == 2


@pytest.mark.django_db
@isolate_apps("games")
def test_a_library_that_never_appended_has_no_stream_to_check(owned_library):
    shelf = declare_and_create_shelf()

    report = rebuild_projections(
        owned_library, wiring=SHADOW_WIRING, apps=shelf._meta.apps
    )

    assert report.stream_id is None
    assert report.replayed_through == 0
    assert report.head_at_diff == 0
    assert report.tables == (
        no_difference(ENTRY_TABLE, rows=0),
        no_difference(SHELF_TABLE, rows=0),
    )


@pytest.mark.django_db
@isolate_apps("games")
def test_rebuilding_a_library_that_never_appended_names_the_stream_it_made(
    owned_library,
):
    """`lock_stream` provisions the head to report."""
    shelf = declare_and_create_shelf()
    seed_shelf(shelf, owned_library, title="left-over")

    report = rebuild_projections(
        owned_library,
        mode=RebuildMode.REBUILD,
        wiring=SHADOW_WIRING,
        apps=shelf._meta.apps,
    )

    assert report.swapped is True
    assert (
        report.stream_id == LibraryEventStreamHead.objects.get(library=owned_library).id
    )
    assert shelf.objects.count() == 0


# --- The management command --------------------------------------------------
#
# Real invocations run every phase, zero tables.
# A canned report covers the rest.


def run_command(*arguments) -> str:
    output = StringIO()
    call_command("rebuild_projections", *arguments, stdout=output)
    return output.getvalue()


def canned_report(**overrides) -> RebuildReport:
    """A report the command can print."""
    report = RebuildReport(
        library_id=uuid7(),
        stream_id=uuid7(),
        mode=RebuildMode.CHECK,
        swapped=False,
        replayed_through=12,
        head_at_diff=12,
        tables=(
            no_difference(ENTRY_TABLE, rows=3),
            TableDiff(
                table=SHELF_TABLE,
                live_rows=5,
                rebuilt_rows=4,
                only_live=2,
                only_rebuilt=1,
                differing=1,
                sample=("abc",),
            ),
        ),
        attempts=(
            RebuildAttempt(
                replayed_through=12,
                replay_seconds=0.1,
                diff_seconds=0.2,
                swap_seconds=None,
                conflict=None,
            ),
        ),
        elapsed_seconds=0.5,
    )
    return replace(report, **overrides)


def reports(report):
    """Stands in for the rebuild itself."""

    def rebuild(library, **options):
        return replace(report, library_id=library.pk, mode=options["mode"])

    return rebuild


@pytest.mark.django_db
def test_the_command_checks_a_library_and_provisions_nothing(owned_library):
    output = run_command(str(owned_library.pk), "--check")

    assert str(owned_library.pk) in output
    assert "0 event" in output
    #: No lock, so no head is provisioned.
    assert not LibraryEventStreamHead.objects.filter(library=owned_library).exists()


@pytest.mark.django_db
def test_the_command_rebuilds_and_says_it_swapped(owned_library):
    output = run_command(str(owned_library.pk))

    assert "Swapped" in output
    assert LibraryEventStreamHead.objects.filter(library=owned_library).exists()


@pytest.mark.django_db
def test_the_command_prints_a_line_per_table(owned_library, monkeypatch):
    monkeypatch.setattr(
        rebuild_command, "rebuild_projections", reports(canned_report())
    )

    output = run_command(str(owned_library.pk), "--check")

    assert "12 event" in output
    assert f"{ENTRY_TABLE}: 3 live, 3 rebuilt" in output
    assert f"{SHELF_TABLE}: 5 live, 4 rebuilt, 2 only live, 1 only rebuilt" in output
    assert "abc" in output
    assert "0.50s" in output
    #: Two only live, one rebuilt, one differing.
    assert "4 row(s)" in output


@pytest.mark.django_db
def test_the_command_flags_a_check_the_head_moved_under(owned_library, monkeypatch):
    monkeypatch.setattr(
        rebuild_command,
        "rebuild_projections",
        reports(canned_report(head_at_diff=14)),
    )

    output = run_command(str(owned_library.pk), "--check")

    assert "advisory" in output


@pytest.mark.django_db
def test_a_rebuild_that_never_swapped_fails_the_command(owned_library, monkeypatch):
    conflicted = canned_report(
        swapped=False,
        attempts=(
            RebuildAttempt(
                replayed_through=12,
                replay_seconds=0.1,
                diff_seconds=0.2,
                swap_seconds=None,
                conflict="The stream was at 12 when it was read and is at 13 now.",
            ),
        ),
    )
    monkeypatch.setattr(rebuild_command, "rebuild_projections", reports(conflicted))

    with pytest.raises(CommandError, match="nothing was swapped"):
        run_command(str(owned_library.pk))


@pytest.mark.django_db
def test_an_unknown_library_fails_without_touching_anything(owned_library):
    with pytest.raises(CommandError, match="No library"):
        run_command(str(uuid7()))

    assert not LibraryEventStreamHead.objects.exists()


@pytest.mark.django_db
def test_a_library_id_that_is_not_a_uuid_fails(owned_library):
    with pytest.raises(CommandError, match="not a library id"):
        run_command("the-one-with-the-games")


# --- Registry hygiene --------------------------------------------------------


@pytest.mark.django_db
def test_this_module_left_the_application_registry_as_it_found_it():
    """Two leak detectors, last and unisolated."""
    #: An unhidden twin reds the live model.
    assert run_checks() == []
    assert {
        relation.key for relation in relation_columns()
    } == EXPECTED_RELATION_COLUMNS
