import uuid
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

pytestmark = pytest.mark.django_db(transaction=True)

BEFORE_EVENT_SCHEMA = ("games", "0022_external_references")
WITH_EVENT_SCHEMA = ("games", "0023_library_event_schema")

PRESERVED_GAME_FIELDS = (
    "library_id",
    "name",
    "sort_name",
    "year_released",
    "platform_id",
    "status",
    "mastered",
    "playtime",
)


@pytest.fixture
def event_schema_migration_harness():
    leaf_nodes = MigrationExecutor(connection).loader.graph.leaf_nodes()
    executor = MigrationExecutor(connection)
    executor.migrate([BEFORE_EVENT_SCHEMA])
    call_command("flush", interactive=False, verbosity=0)
    old_apps = executor.loader.project_state([BEFORE_EVENT_SCHEMA]).apps
    yield old_apps
    call_command("flush", interactive=False, verbosity=0)
    MigrationExecutor(connection).migrate(leaf_nodes)


def migrate_to_event_schema():
    executor = MigrationExecutor(connection)
    executor.migrate([WITH_EVENT_SCHEMA])
    return executor.loader.project_state([WITH_EVENT_SCHEMA]).apps


def migrate_back_to_previous_schema():
    MigrationExecutor(connection).migrate([BEFORE_EVENT_SCHEMA])


def seed_private_and_shared_catalog(apps):
    User = apps.get_model("auth", "User")
    UserLibrary = apps.get_model("games", "UserLibrary")
    Platform = apps.get_model("games", "Platform")
    Game = apps.get_model("games", "Game")

    first_user = User.objects.create(username="event-schema-a")
    second_user = User.objects.create(username="event-schema-b")
    first_library = UserLibrary.objects.create(
        user_id=first_user.pk, created_at=timezone.now()
    )
    second_library = UserLibrary.objects.create(
        user_id=second_user.pk, created_at=timezone.now()
    )
    private_platform = Platform.objects.create(
        library_id=first_library.pk, name="Private event Platform"
    )
    shared_platform = Platform.objects.create(name="Shared event Platform")

    Game.objects.create(
        id=uuid.uuid7(),
        library_id=first_library.pk,
        name="First private",
        sort_name="First private",
        year_released=2001,
        platform_id=private_platform.pk,
        status="p",
        mastered=False,
        playtime=timedelta(hours=3),
    )
    Game.objects.create(
        id=uuid.uuid7(),
        library_id=second_library.pk,
        name="Second private",
        sort_name="Second private",
        year_released=2002,
        platform_id=None,
        status="f",
        mastered=True,
        playtime=timedelta(hours=5),
    )
    Game.objects.create(
        id=uuid.uuid7(),
        library_id=None,
        name="Shared catalog entry",
        sort_name="Shared catalog entry",
        year_released=2003,
        platform_id=shared_platform.pk,
        status="u",
        mastered=False,
        playtime=timedelta(),
    )


def game_snapshot(apps):
    Game = apps.get_model("games", "Game")
    return {
        game.pk: {field: getattr(game, field) for field in PRESERVED_GAME_FIELDS}
        for game in Game.objects.all()
    }


def create_head(apps, library_id):
    StreamHead = apps.get_model("games", "LibraryEventStreamHead")
    return StreamHead.objects.create(id=uuid.uuid7(), library_id=library_id)


def create_event(apps, head):
    LibraryEvent = apps.get_model("games", "LibraryEvent")
    return LibraryEvent.objects.create(
        id=uuid.uuid7(),
        library_id=head.library_id,
        stream_id=head.pk,
        sequence=1,
        event_type="library.probe.recorded",
        aggregate_type="probe",
        aggregate_id=uuid.uuid7(),
        correlation_id=uuid.uuid7(),
        idempotency_key="probe-1",
        payload={},
    )


def first_library_id(apps):
    UserLibrary = apps.get_model("games", "UserLibrary")
    return UserLibrary.objects.order_by("created_at").first().pk


def test_forward_migration_preserves_catalog_data(event_schema_migration_harness):
    old_apps = event_schema_migration_harness
    seed_private_and_shared_catalog(old_apps)
    before = game_snapshot(old_apps)

    new_apps = migrate_to_event_schema()

    assert game_snapshot(new_apps) == before
    Game = new_apps.get_model("games", "Game")
    assert Game.objects.filter(library_id__isnull=True).count() == 1


def test_forward_migration_creates_no_stream_rows(event_schema_migration_harness):
    old_apps = event_schema_migration_harness
    seed_private_and_shared_catalog(old_apps)

    new_apps = migrate_to_event_schema()

    assert new_apps.get_model("games", "LibraryEventStreamHead").objects.count() == 0
    assert new_apps.get_model("games", "LibraryEvent").objects.count() == 0


def test_reverse_migration_succeeds_when_empty(event_schema_migration_harness):
    old_apps = event_schema_migration_harness
    seed_private_and_shared_catalog(old_apps)
    before = game_snapshot(old_apps)
    migrate_to_event_schema()

    migrate_back_to_previous_schema()

    assert game_snapshot(old_apps) == before


def test_reverse_migration_refuses_with_head_rows(event_schema_migration_harness):
    old_apps = event_schema_migration_harness
    seed_private_and_shared_catalog(old_apps)
    new_apps = migrate_to_event_schema()
    create_head(new_apps, first_library_id(new_apps))

    with pytest.raises(RuntimeError, match="stream head"):
        migrate_back_to_previous_schema()

    assert new_apps.get_model("games", "LibraryEventStreamHead").objects.count() == 1


def test_reverse_migration_refuses_with_event_rows(event_schema_migration_harness):
    old_apps = event_schema_migration_harness
    seed_private_and_shared_catalog(old_apps)
    new_apps = migrate_to_event_schema()
    create_event(new_apps, create_head(new_apps, first_library_id(new_apps)))

    with pytest.raises(RuntimeError, match="event"):
        migrate_back_to_previous_schema()

    assert new_apps.get_model("games", "LibraryEvent").objects.count() == 1
