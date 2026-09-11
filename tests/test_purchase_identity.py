import uuid
from datetime import date

import pytest
from django.db import IntegrityError, connection, transaction
from model_schema_scan import models_covered
from ninja import ModelSchema

from games import api as api_module
from games.forms import PurchaseForm
from games.models import Purchase
from timetracker.uuidv7 import UUIDv7Field

pytestmark = pytest.mark.django_db(transaction=True)


PURCHASED_ON = date(2024, 6, 1)


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
    values = [field.get_prep_value(field.pre_save(instance, True)) for field in fields]
    with connection.cursor() as cursor:
        cursor.execute(
            f'INSERT INTO "{model._meta.db_table}" ({columns}) '
            f'VALUES ({placeholders}) RETURNING "id"',
            values,
        )
        return uuid.UUID(str(cursor.fetchone()[0]))


def make_purchase(library, **overrides):
    field_values = {
        "library": library,
        "date_purchased": PURCHASED_ON,
        "price": 10.0,
        "price_currency": "USD",
    } | overrides
    return Purchase.objects.create(**field_values)


# --- Field contract ---------------------------------------------------------


def test_purchase_created_through_the_orm_gets_a_distinct_version_7_uuid(
    owned_library,
):
    first = make_purchase(owned_library, name="First")
    second = make_purchase(owned_library, name="Second")
    assert first.pk.version == 7
    assert second.pk.version == 7
    assert first.pk != second.pk


def test_raw_purchase_insert_omitting_id_gets_the_database_default(owned_library):
    purchase_uuid = raw_insert_without_identity(
        Purchase,
        library=owned_library,
        date_purchased=PURCHASED_ON,
        price=10.0,
        price_currency="USD",
        name="Raw Purchase",
    )
    assert purchase_uuid.version == 7
    assert Purchase.objects.get(pk=purchase_uuid).name == "Raw Purchase"


def test_database_rejects_a_duplicate_purchase_uuid(owned_library):
    shared = uuid.uuid7()
    make_purchase(owned_library, name="First", id=shared)
    with pytest.raises(IntegrityError), transaction.atomic():
        make_purchase(owned_library, name="Second", id=shared)


def test_database_rejects_a_non_v7_purchase_uuid(owned_library):
    with pytest.raises(IntegrityError), transaction.atomic():
        make_purchase(owned_library, name="Bad", id=uuid.uuid4())


# --- Invisibility ------------------------------------------------------------


def test_uuid_is_absent_from_purchase_form_fields():
    assert "uuid" not in PurchaseForm.base_fields


def test_no_model_schema_generates_fields_from_purchase():
    """The "no API leak" argument rests on no `ModelSchema` covering `Purchase`
    - every purchase-shaped response is a hand-enumerated `Schema`. Pin that
    premise so adding a `ModelSchema` over `Purchase` fails here instead of
    silently publishing the new column.
    """

    class PurchaseProbe(ModelSchema):
        class Meta:
            model = Purchase
            fields = ("name",)

    #: No `ModelSchema` is left to find.
    #: The probe says the scan would find one.
    assert models_covered({"probe": PurchaseProbe}) == {Purchase}

    assert Purchase not in models_covered(vars(api_module))


def test_the_model_declares_one_uuidv7_primary_key_and_no_second_uuid_field():
    assert isinstance(Purchase._meta.pk, UUIDv7Field)
    assert Purchase._meta.pk.name == "id"
    assert Purchase._meta.pk.primary_key is True
    assert Purchase._meta.pk.editable is False
    assert Purchase._meta.pk.serialize is False
    assert "uuid" not in {field.name for field in Purchase._meta.local_fields}
