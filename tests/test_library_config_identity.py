import uuid

import pytest
from django.db import IntegrityError, connection, transaction
from model_schema_scan import models_covered
from ninja import ModelSchema

from games import api as api_module
from games.forms import DeviceForm
from games.models import Device, FilterPreset, Session, UserLibraryPreferences
from timetracker.uuidv7 import UUIDv7Field

pytestmark = pytest.mark.django_db(transaction=True)


def raw_insert_without_identity(model, **field_values):
    """INSERT a row through raw SQL that omits the `id` column entirely,
    so PostgreSQL's own `uuidv7()` column default fills it in - the only
    way to exercise `db_default`, since the ORM always resolves the field's
    Python `default` first and never leaves the column to the database.
    """
    instance = model(**field_values)
    fields = [
        field
        for field in model._meta.local_concrete_fields
        if not field.primary_key and not field.generated
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
            f'VALUES ({placeholders}) RETURNING "id"',
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
    assert first.pk.version == 7
    assert second.pk.version == 7
    assert first.pk != second.pk


def test_filterpreset_created_through_the_orm_gets_a_distinct_version_7_uuid(
    owned_library,
):
    first = make_preset(owned_library, name="First")
    second = make_preset(owned_library, name="Second")
    assert first.pk.version == 7
    assert second.pk.version == 7
    assert first.pk != second.pk


def test_raw_device_insert_omitting_uuid_gets_the_database_default(owned_library):
    device_uuid = raw_insert_without_identity(
        Device, library=owned_library, name="Raw Device"
    )
    assert device_uuid.version == 7
    assert Device.objects.get(pk=device_uuid).name == "Raw Device"


def test_raw_filterpreset_insert_omitting_uuid_gets_the_database_default(owned_library):
    preset_uuid = raw_insert_without_identity(
        FilterPreset, library=owned_library, name="Raw Preset", mode="games"
    )
    assert preset_uuid.version == 7
    assert FilterPreset.objects.get(pk=preset_uuid).name == "Raw Preset"


def test_database_rejects_a_duplicate_device_uuid(owned_library):
    shared = uuid.uuid7()
    make_device(owned_library, name="First", id=shared)
    with pytest.raises(IntegrityError), transaction.atomic():
        make_device(owned_library, name="Second", id=shared)


def test_database_rejects_a_duplicate_filterpreset_uuid(owned_library):
    shared = uuid.uuid7()
    make_preset(owned_library, name="First", id=shared)
    with pytest.raises(IntegrityError), transaction.atomic():
        make_preset(owned_library, name="Second", id=shared)


def test_database_rejects_a_non_v7_device_uuid(owned_library):
    with pytest.raises(IntegrityError), transaction.atomic():
        make_device(owned_library, name="Bad", id=uuid.uuid4())


def test_database_rejects_a_non_v7_filterpreset_uuid(owned_library):
    with pytest.raises(IntegrityError), transaction.atomic():
        make_preset(owned_library, name="Bad", id=uuid.uuid4())


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

    class DeviceProbe(ModelSchema):
        class Meta:
            model = Device
            fields = ("name",)

    #: No `ModelSchema` is left to find.
    #: The probe says the scan would find one.
    assert models_covered({"probe": DeviceProbe}) == {Device}

    covered = models_covered(vars(api_module))
    assert Device not in covered
    assert FilterPreset not in covered


def test_uuid_is_absent_from_device_out_fields():
    assert "uuid" not in api_module.DeviceOut.model_fields


def test_uuid_is_absent_from_preset_option_and_preset_in_fields():
    assert "uuid" not in api_module.PresetOption.model_fields
    assert "uuid" not in api_module.PresetIn.model_fields


def test_both_models_declare_one_uuidv7_primary_key_every_relation_names():
    for model in (Device, FilterPreset):
        assert isinstance(model._meta.pk, UUIDv7Field)
        assert model._meta.pk.name == "id"
        assert model._meta.pk.primary_key is True
        assert model._meta.pk.editable is False
        assert model._meta.pk.serialize is False
        assert "uuid" not in {field.name for field in model._meta.local_fields}

    assert Session._meta.get_field("device").remote_field.field_name == "id"
    assert (
        UserLibraryPreferences._meta.get_field("default_device").remote_field.field_name
        == "id"
    )


def test_setting_the_same_default_device_twice_writes_once(owned_library):
    device = Device.objects.create(library=owned_library, name="Default device")
    preferences = owned_library.preferences

    assert preferences.set_default_device(device) is True
    assert preferences.set_default_device(device) is False
