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

from games.events.append import lock_stream
from games.events.envelope import RecordedEvent
from games.events.projection import (
    HandlerMap,
    Projector,
    ProjectorFamily,
    ProjectorRegistry,
)
from games.events.rebuild import (
    LiveWriteRefused,
    insertable_columns,
    only_shadow_writes,
    projection_models,
    replay_into_shadow,
    shadow_tables,
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


def seed_shelf(model, library, *, title="seeded"):
    return model.objects.create(id=uuid4(), library_id=library.pk, title=title)


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
