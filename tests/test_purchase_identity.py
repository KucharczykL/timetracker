import uuid
from datetime import UTC, date, datetime

import pytest
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone
from ninja import ModelSchema

from games import api as api_module
from games.forms import PurchaseForm
from games.models import Purchase

pytestmark = pytest.mark.django_db(transaction=True)

BEFORE_IDENTITY = ("games", "0006_session_playhistory_uuid_identity")
WITH_IDENTITY = ("games", "0007_purchase_uuid_identity")

PURCHASED_ON = date(2024, 6, 1)


def floor_ms(moment: datetime) -> int:
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    elapsed = moment - epoch
    return (
        elapsed.days * 86_400_000
        + elapsed.seconds * 1000
        + elapsed.microseconds // 1000
    )


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
        if getattr(getattr(schema, "Meta", None), "model", None) is Purchase
    ] == []


# --- Migration: forward backfill --------------------------------------------


def table_columns(table_name: str) -> set[str]:
    with connection.cursor() as cursor:
        description = connection.introspection.get_table_description(cursor, table_name)
    return {column.name for column in description}


def create_purchase_at(apps, library, *, name: str, created_at: datetime):
    """Create a historical-model row and force its `auto_now_add` `created_at`."""
    Purchase = apps.get_model("games", "Purchase")
    purchase = Purchase.objects.create(
        library_id=library.pk,
        name=name,
        date_purchased=PURCHASED_ON,
        price=10.0,
        price_currency="USD",
    )
    Purchase.objects.filter(pk=purchase.pk).update(created_at=created_at)
    purchase.refresh_from_db()
    return purchase


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

    # purchase_late is created first (lowest pk) but stamped with the latest
    # created_at, so order_by("created_at", "pk") must disagree with
    # creation/pk order - the "one row out of primary-key order" case.
    purchase_late = create_purchase_at(apps, library, name="Late", created_at=later)
    purchase_tied_a = create_purchase_at(
        apps, library, name="TiedA", created_at=tied_ms
    )
    purchase_tied_b = create_purchase_at(
        apps, library, name="TiedB", created_at=tied_ms
    )

    new_apps = migrate_to_identity()
    MigratedPurchase = new_apps.get_model("games", "Purchase")

    purchases = list(MigratedPurchase.objects.order_by("pk"))
    assert all(purchase.uuid is not None for purchase in purchases)
    assert len({purchase.uuid for purchase in purchases}) == len(purchases)
    assert all(purchase.uuid.version == 7 for purchase in purchases)
    for purchase in purchases:
        assert purchase.uuid.time == floor_ms(purchase.created_at)

    assert list(
        MigratedPurchase.objects.order_by("uuid").values_list("pk", flat=True)
    ) == list(
        MigratedPurchase.objects.order_by("created_at", "pk").values_list(
            "pk", flat=True
        )
    )
    assert list(
        MigratedPurchase.objects.order_by("uuid").values_list("pk", flat=True)
    ) == [purchase_tied_a.pk, purchase_tied_b.pk, purchase_late.pk]

    output = capsys.readouterr().out
    assert "PUR identity backfilled" in output
    assert "purchase_rows=3 purchase_distinct=3" in output
    assert "max_timestamp_delta_ms=0 order_preserved=true" in output


# --- Migration: reverse -------------------------------------------------------


def test_reverse_migration_drops_the_column_and_keeps_other_data(identity_harness):
    apps = identity_harness
    library = seed_library(apps, username="reverse-owner")
    purchase = create_purchase_at(
        apps, library, name="Persistent Purchase", created_at=timezone.now()
    )

    new_apps = migrate_to_identity()
    assert new_apps.get_model("games", "Purchase").objects.get(pk=purchase.pk).uuid

    executor = MigrationExecutor(connection)
    executor.migrate([BEFORE_IDENTITY])
    reverted_apps = executor.loader.project_state([BEFORE_IDENTITY]).apps

    assert "uuid" not in table_columns("games_purchase")

    RevertedPurchase = reverted_apps.get_model("games", "Purchase")
    assert RevertedPurchase.objects.get(pk=purchase.pk).name == "Persistent Purchase"
