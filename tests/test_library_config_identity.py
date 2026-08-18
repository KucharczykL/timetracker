import uuid
from datetime import UTC, datetime

import pytest
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone
from ninja import ModelSchema

from games import api as api_module
from games.forms import DeviceForm
from games.models import Device, FilterPreset

pytestmark = pytest.mark.django_db(transaction=True)

BEFORE_IDENTITY = ("games", "0007_purchase_uuid_identity")
WITH_IDENTITY = ("games", "0008_library_config_uuid_identity")


def floor_ms(moment: datetime) -> int:
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    elapsed = moment - epoch
    return (
        elapsed.days * 86_400_000
        + elapsed.seconds * 1000
        + elapsed.microseconds // 1000
    )


def raw_insert_without_uuid(model, **field_values):
    """INSERT a row through raw SQL that omits the `uuid` column entirely,
    so PostgreSQL's own `uuidv7()` column default fills it in - the only
    way to exercise `db_default`, since the ORM always resolves the field's
    Python `default` first and never leaves the column to the database.
    """
    instance = model(**field_values)
    fields = [
        field
        for field in model._meta.local_concrete_fields
        if field.name != "uuid" and not field.primary_key and not field.generated
    ]
    columns = ", ".join(f'"{field.column}"' for field in fields)
    placeholders = ", ".join(["%s"] * len(fields))
    # pre_save() resolves auto_now/auto_now_add fields the way a real save
    # would; every other field returns its already-set attribute value.
    # get_db_prep_save (not get_prep_value) is required so JSONField values
    # (FilterPreset.find_filter/object_filter/ui_options) get adapted to a
    # form psycopg can bind, matching what the ORM's insert compiler does.
    values = [
        field.get_db_prep_save(field.pre_save(instance, True), connection)
        for field in fields
    ]
    with connection.cursor() as cursor:
        cursor.execute(
            f'INSERT INTO "{model._meta.db_table}" ({columns}) '
            f'VALUES ({placeholders}) RETURNING "uuid"',
            values,
        )
        return uuid.UUID(str(cursor.fetchone()[0]))


def make_device(library, **overrides):
    field_values = {"library": library, "name": "Living Room PC"} | overrides
    return Device.objects.create(**field_values)


def make_preset(library, **overrides):
    field_values = {
        "library": library,
        "name": "My Preset",
        "mode": "games",
    } | overrides
    return FilterPreset.objects.create(**field_values)


# --- Field contract ---------------------------------------------------------


def test_device_created_through_the_orm_gets_a_distinct_version_7_uuid(owned_library):
    first = make_device(owned_library, name="First")
    second = make_device(owned_library, name="Second")
    assert first.uuid.version == 7
    assert second.uuid.version == 7
    assert first.uuid != second.uuid


def test_filterpreset_created_through_the_orm_gets_a_distinct_version_7_uuid(
    owned_library,
):
    first = make_preset(owned_library, name="First")
    second = make_preset(owned_library, name="Second")
    assert first.uuid.version == 7
    assert second.uuid.version == 7
    assert first.uuid != second.uuid


def test_raw_device_insert_omitting_uuid_gets_the_database_default(owned_library):
    device_uuid = raw_insert_without_uuid(
        Device, library=owned_library, name="Raw Device"
    )
    assert device_uuid.version == 7
    assert Device.objects.get(uuid=device_uuid).name == "Raw Device"


def test_raw_filterpreset_insert_omitting_uuid_gets_the_database_default(owned_library):
    preset_uuid = raw_insert_without_uuid(
        FilterPreset, library=owned_library, name="Raw Preset", mode="games"
    )
    assert preset_uuid.version == 7
    assert FilterPreset.objects.get(uuid=preset_uuid).name == "Raw Preset"


def test_database_rejects_a_duplicate_device_uuid(owned_library):
    shared = uuid.uuid7()
    make_device(owned_library, name="First", uuid=shared)
    with pytest.raises(IntegrityError), transaction.atomic():
        make_device(owned_library, name="Second", uuid=shared)


def test_database_rejects_a_duplicate_filterpreset_uuid(owned_library):
    shared = uuid.uuid7()
    make_preset(owned_library, name="First", uuid=shared)
    with pytest.raises(IntegrityError), transaction.atomic():
        make_preset(owned_library, name="Second", uuid=shared)


def test_database_rejects_a_non_v7_device_uuid(owned_library):
    with pytest.raises(IntegrityError), transaction.atomic():
        make_device(owned_library, name="Bad", uuid=uuid.uuid4())


def test_database_rejects_a_non_v7_filterpreset_uuid(owned_library):
    with pytest.raises(IntegrityError), transaction.atomic():
        make_preset(owned_library, name="Bad", uuid=uuid.uuid4())


# --- Invisibility ------------------------------------------------------------


def test_uuid_is_absent_from_device_form_fields():
    assert "uuid" not in DeviceForm.base_fields


def test_no_model_schema_generates_fields_from_device_or_filterpreset():
    """The "no API leak" argument rests on no `ModelSchema` covering `Device`
    or `FilterPreset` - every response involving them is a hand-enumerated
    `Schema` (`DeviceOut`, `PresetOption`, `PresetIn`). Pin that premise so
    adding a `ModelSchema` over either model fails here instead of silently
    publishing the new column.
    """
    model_schemas = [
        member
        for member in vars(api_module).values()
        if isinstance(member, type)
        and issubclass(member, ModelSchema)
        and member is not ModelSchema
    ]
    # Guard against the scan passing because it found nothing to look at.
    assert model_schemas
    assert [
        schema
        for schema in model_schemas
        if getattr(getattr(schema, "Meta", None), "model", None)
        in (Device, FilterPreset)
    ] == []


def test_uuid_is_absent_from_device_out_fields():
    assert "uuid" not in api_module.DeviceOut.model_fields


def test_uuid_is_absent_from_preset_option_and_preset_in_fields():
    assert "uuid" not in api_module.PresetOption.model_fields
    assert "uuid" not in api_module.PresetIn.model_fields


# --- Migration: forward backfill --------------------------------------------


def table_columns(table_name: str) -> set[str]:
    with connection.cursor() as cursor:
        description = connection.introspection.get_table_description(cursor, table_name)
    return {column.name for column in description}


def create_row_at(apps, model_name: str, *, created_at: datetime, **field_values):
    """Create a historical-model row and force its `auto_now_add` `created_at`."""
    model = apps.get_model("games", model_name)
    row = model.objects.create(**field_values)
    model.objects.filter(pk=row.pk).update(created_at=created_at)
    row.refresh_from_db()
    return row


@pytest.fixture
def identity_harness():
    # Migrating down to BEFORE_IDENTITY unapplies every later migration too, so
    # the restore target is the graph's leaf nodes rather than WITH_IDENTITY,
    # which would strand this worker's shared database behind head for every
    # later test that reuses it.
    leaf_nodes = MigrationExecutor(connection).loader.graph.leaf_nodes()
    executor = MigrationExecutor(connection)
    executor.migrate([BEFORE_IDENTITY])
    call_command("flush", interactive=False, verbosity=0)
    old_apps = executor.loader.project_state([BEFORE_IDENTITY]).apps
    yield old_apps
    MigrationExecutor(connection).migrate(leaf_nodes)


def migrate_to_identity():
    executor = MigrationExecutor(connection)
    executor.migrate([WITH_IDENTITY])
    return executor.loader.project_state([WITH_IDENTITY]).apps


def seed_library(apps, *, username: str):
    User = apps.get_model("auth", "User")
    UserLibrary = apps.get_model("games", "UserLibrary")
    user = User.objects.create(username=username)
    return UserLibrary.objects.create(user_id=user.pk, created_at=timezone.now())


def test_forward_migration_backfills_every_row_with_a_distinct_ordered_uuid(
    identity_harness, capsys
):
    apps = identity_harness
    library = seed_library(apps, username="identity-owner")

    tied_ms = datetime(2024, 6, 1, 12, 0, 0, 500_000, tzinfo=UTC)
    later = datetime(2024, 6, 1, 12, 0, 1, 0, tzinfo=UTC)

    # device_late is created first (lowest pk) but stamped with the latest
    # created_at, so order_by("created_at", "pk") must disagree with
    # creation/pk order - the "one row out of primary-key order" case.
    device_late = create_row_at(
        apps, "Device", library_id=library.pk, name="Late", created_at=later
    )
    device_tied_a = create_row_at(
        apps, "Device", library_id=library.pk, name="TiedA", created_at=tied_ms
    )
    device_tied_b = create_row_at(
        apps, "Device", library_id=library.pk, name="TiedB", created_at=tied_ms
    )

    preset_tied_a = create_row_at(
        apps,
        "FilterPreset",
        library_id=library.pk,
        name="TiedA",
        mode="games",
        created_at=tied_ms,
    )
    preset_tied_b = create_row_at(
        apps,
        "FilterPreset",
        library_id=library.pk,
        name="TiedB",
        mode="games",
        created_at=tied_ms,
    )
    preset_late = create_row_at(
        apps,
        "FilterPreset",
        library_id=library.pk,
        name="Late",
        mode="games",
        created_at=later,
    )

    new_apps = migrate_to_identity()
    MigratedDevice = new_apps.get_model("games", "Device")
    MigratedFilterPreset = new_apps.get_model("games", "FilterPreset")

    devices = list(MigratedDevice.objects.order_by("pk"))
    presets = list(MigratedFilterPreset.objects.order_by("pk"))

    for rows in (devices, presets):
        assert all(row.uuid is not None for row in rows)
        assert len({row.uuid for row in rows}) == len(rows)
        assert all(row.uuid.version == 7 for row in rows)
        for row in rows:
            assert row.uuid.time == floor_ms(row.created_at)

    for model in (MigratedDevice, MigratedFilterPreset):
        assert list(
            model.objects.order_by("uuid").values_list("pk", flat=True)
        ) == list(
            model.objects.order_by("created_at", "pk").values_list("pk", flat=True)
        )

    assert list(
        MigratedDevice.objects.order_by("uuid").values_list("pk", flat=True)
    ) == [device_tied_a.pk, device_tied_b.pk, device_late.pk]
    assert list(
        MigratedFilterPreset.objects.order_by("uuid").values_list("pk", flat=True)
    ) == [preset_tied_a.pk, preset_tied_b.pk, preset_late.pk]

    output = capsys.readouterr().out
    assert "LIB identity backfilled" in output
    assert "device_rows=3 device_distinct=3" in output
    assert "filterpreset_rows=3 filterpreset_distinct=3" in output
    assert "max_timestamp_delta_ms=0 order_preserved=true" in output


def test_forward_migration_handles_an_empty_filterpreset_table(
    identity_harness, capsys
):
    """Production has zero `FilterPreset` rows today - the backfill and
    reconciliation must not assume at least one row exists.
    """
    apps = identity_harness
    library = seed_library(apps, username="empty-preset-owner")
    create_row_at(
        apps,
        "Device",
        library_id=library.pk,
        name="Only Device",
        created_at=timezone.now(),
    )

    new_apps = migrate_to_identity()
    MigratedFilterPreset = new_apps.get_model("games", "FilterPreset")
    assert MigratedFilterPreset.objects.count() == 0

    output = capsys.readouterr().out
    assert "filterpreset_rows=0 filterpreset_distinct=0" in output


# --- Migration: reverse -------------------------------------------------------


def test_reverse_migration_drops_the_columns_and_keeps_other_data(identity_harness):
    apps = identity_harness
    library = seed_library(apps, username="reverse-owner")
    device = create_row_at(
        apps,
        "Device",
        library_id=library.pk,
        name="Persistent Device",
        created_at=timezone.now(),
    )
    preset = create_row_at(
        apps,
        "FilterPreset",
        library_id=library.pk,
        name="Persistent Preset",
        mode="games",
        created_at=timezone.now(),
    )

    new_apps = migrate_to_identity()
    assert new_apps.get_model("games", "Device").objects.get(pk=device.pk).uuid
    assert new_apps.get_model("games", "FilterPreset").objects.get(pk=preset.pk).uuid

    executor = MigrationExecutor(connection)
    executor.migrate([BEFORE_IDENTITY])
    reverted_apps = executor.loader.project_state([BEFORE_IDENTITY]).apps

    assert "uuid" not in table_columns("games_device")
    assert "uuid" not in table_columns("games_filterpreset")

    RevertedDevice = reverted_apps.get_model("games", "Device")
    RevertedFilterPreset = reverted_apps.get_model("games", "FilterPreset")
    assert RevertedDevice.objects.get(pk=device.pk).name == "Persistent Device"
    assert RevertedFilterPreset.objects.get(pk=preset.pk).name == "Persistent Preset"
