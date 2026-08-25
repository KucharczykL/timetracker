"""Rebuilding a library's projections into shadow tables and swapping them in.

The models are declared under `isolate_apps("games")` and created with
`schema_editor`, and the rebuild is called with `apps=<model>._meta.apps`:
`isolate_apps` patches `Options.default_apps` and leaves the global registry
alone, so a rebuild reading `django.apps.apps` would discover zero tables here
and every assertion below would pass over nothing.

Isolation is not housekeeping either. An un-isolated `app_label = "games"`
model — or a process-cached twin of one — joins the registry
`games/identity_audit.py` reads, where `tests/test_uuid_identity_audit.py`
asserts set equality against a pinned list.
"""

from collections.abc import Callable
from typing import Any, ClassVar, TypedDict
from uuid import UUID, uuid4, uuid7

import pytest
from django.db import connection, transaction
from django.test.utils import isolate_apps
from pydantic import ConfigDict, with_config
from test_projection_targets import ENTRY_TABLE, SHELF_TABLE, declare_projection_models

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
    TableDiff,
    diff_table,
    diff_tables,
    insertable_columns,
    only_shadow_writes,
    projection_models,
    replay_into_shadow,
    shadow_tables,
    swap_in,
)
from games.events.replay import ReplayResult, StreamNotContiguous
from games.events.targets import SHADOW_SUFFIX, ShadowTarget
from games.events.vocabulary import EventSpec, EventTypeRegistry, NewEvent
from games.events.wiring import EventWiring
from games.models import (
    LibraryEvent,
    LibraryEventStreamHead,
    ProjectionModel,
    UserLibrary,
)


def create_tables(*models: type[ProjectionModel]) -> None:
    """The tables, for the length of the test.

    Nothing drops them: the test runs inside pytest-django's transaction, and
    PostgreSQL rolls DDL back with everything else.
    """
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

    #: A twin is a projection model and is in the registry, so only its
    #: `managed = False` keeps it from being rebuilt as a table of its own.
    assert set(projection_models(shelf._meta.apps)) == {shelf, entry}


def test_the_application_declares_no_projection_table_yet():
    """The honest answer for the current state: the families that own real
    projection tables are a later issue, and this one rebuilds none of them."""
    assert projection_models() == ()


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
        #: A family reads back rows it just wrote, at whatever selectivity the
        #: live table was designed for.
        assert index_count(shadow_of(SHELF_TABLE)) == index_count(f'"{SHELF_TABLE}"')
        assert index_count(shadow_of(SHELF_TABLE)) > 1


@pytest.mark.django_db
@isolate_apps("games")
def test_a_shadow_table_carries_no_foreign_key():
    shelf, entry = declare_projection_models()
    create_tables(shelf, entry)

    with shadow_tables([shelf, entry]):
        #: `LIKE ... INCLUDING ALL` leaves foreign keys behind, which is what
        #: lets the shadows be filled in any order: the reference that has to
        #: hold is the one in the live table after the swap.
        assert foreign_key_count(f'"{ENTRY_TABLE}"') == 2
        assert foreign_key_count(shadow_of(ENTRY_TABLE)) == 0


@pytest.mark.django_db
@isolate_apps("games")
def test_the_insertable_columns_are_the_tables_own_minus_the_generated_one():
    shelf, _ = declare_projection_models()
    create_tables(shelf)

    columns = table_columns(f'"{SHELF_TABLE}"')

    assert "played_minutes" in columns
    #: PostgreSQL refuses to be handed a generated column and recomputes it
    #: identically from the ones that are carried.
    assert insertable_columns(shelf) == tuple(
        column for column in columns if column != "played_minutes"
    )


# --- The write guard --------------------------------------------------------
#
# One test per write path, because a signal-based guard passes the first of them
# and misses the rest -- which is the whole reason the guard is an
# `execute_wrapper` and not a `pre_save` receiver.

type WritePath = Callable[[type[ProjectionModel], UserLibrary], None]


def seed_shelf(model, library, **overrides):
    """One row in whichever shelf table is passed -- live or shadow.

    `played_seconds` is nonzero by default so the generated column carries a
    value on both sides of a diff rather than agreeing at zero.
    """
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

    #: Not the shelf table by name: a cascading delete reaches the child table
    #: first, and which table a path names first is not what is under test.
    with only_shadow_writes(), pytest.raises(LiveWriteRefused, match="not a shadow"):
        write(shelf, owned_library)


@pytest.mark.parametrize("write", WRITE_PATHS, ids=WRITE_PATH_NAMES)
@pytest.mark.django_db
@isolate_apps("games")
def test_a_write_path_works_again_once_the_block_exits(write, owned_library):
    shelf, entry = declare_projection_models()
    create_tables(shelf, entry)
    seed_shelf(shelf, owned_library)

    #: The refusal is raised through Django's own `atomic(savepoint=False)`
    #: around a write, which marks the transaction for rollback on any
    #: exception. A savepoint of its own contains that, the way phase 2's
    #: transaction contains it in production.
    with only_shadow_writes(), pytest.raises(LiveWriteRefused), transaction.atomic():
        write(shelf, owned_library)

    #: The guard is phase-local: another rebuild phase, and every other process,
    #: keeps writing live projections throughout.
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
        #: A rebuild reads live rows in the phase after this one, and a family
        #: may read anything it likes; only writing is refused.
        assert shelf.objects.count() == 1


@pytest.mark.django_db
def test_the_guard_refuses_a_write_to_a_table_no_rebuild_touches(owned_library):
    """An allowlist, not a list of the tables being rebuilt.

    The side effect nobody would have listed -- a family bumping a counter row,
    filling a cache table, or recording an audit row outside its target -- is
    what makes "check mode writes nothing" true by construction. In check mode
    and on every discarded attempt, such a write would otherwise commit and stay.
    """
    with only_shadow_writes(), pytest.raises(LiveWriteRefused, match="userlibrary"):
        UserLibrary.objects.filter(pk=owned_library.pk).update(
            created_at=owned_library.created_at
        )


# --- Phase 2: the replay ----------------------------------------------------
#
# The families below register into registries this module owns, so nothing
# declared here reaches `DEFAULT_REGISTRY` or another test.


@with_config(ConfigDict(extra="forbid", strict=True))
class ShelfPayload(TypedDict):
    title: str


PROBE_SHELVED = EventSpec(
    "library.probe.shelved", aggregate_type="probe", payload=ShelfPayload
)
EVENT_TYPES = EventTypeRegistry()
EVENT_TYPES.register(PROBE_SHELVED)

#: The shelf model the running test declared. A family is registered once, at
#: import, while `isolate_apps` builds a new class per test -- which is the
#: production shape read backwards: there a family names its model at import
#: and a rebuild redirects the class it is handed.
DECLARED_SHELF: list[type[ProjectionModel]] = []


def declared_shelf() -> Any:
    """The shelf model the running test declared.

    Typed loosely because `objects` is added to concrete models and
    `ProjectionModel` is abstract, so the precise type has no manager on it.
    """
    return DECLARED_SHELF[-1]


shadow_registry = ProjectorRegistry()
live_writing_registry = ProjectorRegistry()


class Shelver(Projector, registry=shadow_registry):
    """A family written the way #671's will be: it writes its target."""

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
    """A family that writes its live model, target or no target."""

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
    """One append carrying an event per title, folded through `wiring`."""
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

        #: The parity the whole issue is about: the same families over the same
        #: events reach the state the append path wrote row by row.
        assert shelf_rows(twin) == live_rows

    assert shelf_rows(shelf) == live_rows
    assert result.folded_through == head_sequence(owned_library)


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
    """`StreamNotContiguous` arrives with its own type.

    A phase that wrapped it would tell `run_in_transaction` to decide from the
    wrapper, and a stream with a hole in it is not a thing another attempt fixes.
    """
    shelf = declare_and_create_shelf()
    append_shelved(owned_library, ["one", "two", "three"])
    LibraryEvent.objects.filter(library=owned_library, sequence=2).delete()

    with shadow_tables([shelf]), pytest.raises(StreamNotContiguous, match="2"):
        replay_into_shadow(owned_library, [shelf], wiring=SHADOW_WIRING)


@pytest.mark.django_db
@isolate_apps("games")
def test_a_library_that_never_appended_folds_nothing(owned_library):
    shelf = declare_and_create_shelf()
    twin = ShadowTarget().model(shelf)

    with shadow_tables([shelf]):
        result = replay_into_shadow(owned_library, [shelf], wiring=SHADOW_WIRING)

        assert shelf_rows(twin) == []

    assert result == ReplayResult(stream_id=None, folded_through=0)


@pytest.mark.django_db
@isolate_apps("games")
def test_the_replay_refuses_to_run_without_its_shadow_tables(owned_library):
    """The phase names what is missing.

    Its shadow tables are the caller's to create, and a temp table that was
    never created -- or that a `connection.close()` between phases took with it
    -- would otherwise surface as a bare "relation does not exist" from
    whichever family wrote first.
    """
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

        #: The generated column is compared with the rest and agrees by
        #: construction: both sides computed it from the same seconds.
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
    #: Scoping the library in `WHERE` instead of a subquery would degrade the
    #: outer join and hide exactly this row.
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
    """The null-safety pin.

    `ROW(live.a, ...) <> ROW(shadow.a, ...)` returns NULL when either side holds
    a NULL and the row is dropped, so a column that drifted to or from NULL
    would be reported as matching. Whole-row `IS DISTINCT FROM` is composite
    comparison and is null-safe.
    """
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
    #: Enough to act on, bounded so a wholly-drifted table cannot produce a
    #: report nobody can read.
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

#: One `DELETE` and one `INSERT ... SELECT` per table, whatever the rows.
SWAP_STATEMENTS_PER_TABLE = 2
#: The lock, the head read, and the savepoint pair `transaction.atomic()` opens
#: inside the transaction a test already runs in.
SWAP_FIXED_STATEMENTS = 4


def every_column(model, library) -> list[tuple[Any, ...]]:
    """Every row this library owns, every column, so "unchanged" is literal."""
    columns = [field.name for field in model._meta.concrete_fields]
    return sorted(model.objects.filter(library_id=library.pk).values_list(*columns))


@pytest.mark.django_db
@isolate_apps("games")
def test_the_swap_replaces_the_live_rows_with_the_rebuilt_ones(owned_library):
    """Every way a projection can be wrong, corrected in one swap.

    A row that drifted, a row that was lost, and a row that belongs to nothing
    -- the delete-and-reinsert handles all three without knowing which happened.
    """
    shelf = declare_and_create_shelf()
    append_shelved(owned_library, ["one", "two", "three"])
    correct = shelf_rows(shelf)
    shelf.objects.filter(title="one").update(title="drifted")
    shelf.objects.filter(title="two").delete()
    stray = seed_shelf(shelf, owned_library, title="never-appended")

    with shadow_tables([shelf]):
        replayed = replay_into_shadow(owned_library, [shelf], wiring=SHADOW_WIRING)
        swap_in(owned_library, [shelf], replayed.folded_through)

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
        swap_in(owned_library, [shelf], replayed.folded_through)

    #: Every column, not the count: the swap scopes its delete by library, and a
    #: scope that reached too far would show up here as rows going missing.
    assert every_column(shelf, second_library) == theirs


@pytest.mark.django_db
@isolate_apps("games")
def test_an_event_that_landed_during_the_rebuild_refuses_the_swap(owned_library):
    """The expectation is asserted before anything is written.

    The shadow is a projection of a prefix of the stream, so swapping it in
    would drop the event that landed. The attempt is the thing to redo, which
    Task 9 does; here the swap only has to refuse and leave live alone.
    """
    shelf = declare_and_create_shelf()
    append_shelved(owned_library, ["one"])

    with shadow_tables([shelf]):
        replayed = replay_into_shadow(owned_library, [shelf], wiring=SHADOW_WIRING)
        append_shelved(owned_library, ["landed-late"])
        live_rows = shelf_rows(shelf)

        with pytest.raises(StreamSequenceMismatch) as conflict:
            swap_in(owned_library, [shelf], replayed.folded_through)

    assert conflict.value.expected == replayed.folded_through
    assert conflict.value.actual == head_sequence(owned_library)
    assert shelf_rows(shelf) == live_rows


@pytest.mark.django_db
@isolate_apps("games")
def test_a_library_that_never_appended_is_swapped_empty(owned_library):
    """An empty stream projects to no rows, and the swap says so.

    `lock_stream` provisions the head row a `replay` refuses to create: a
    rebuild is a writer, and `require_sequence(0)` is its assertion that the
    library is still empty.
    """
    shelf = declare_and_create_shelf()
    seed_shelf(shelf, owned_library, title="left-over")

    with shadow_tables([shelf]):
        replayed = replay_into_shadow(owned_library, [shelf], wiring=SHADOW_WIRING)
        swap_in(owned_library, [shelf], replayed.folded_through)

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
        swap_in(owned_library, [shelf, entry], replayed.folded_through)

    #: No family projects the entry table, so its rebuilt state is empty --
    #: which is the point: a table the swap is given is replaced, not topped up.
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
            swap_in(owned_library, [shelf], replayed.folded_through)
