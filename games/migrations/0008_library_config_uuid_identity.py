from datetime import UTC, datetime

from django.db import connection, migrations

from timetracker.uuidv7 import UUIDv7Field, uuid7_at

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

# Every model converted by an earlier issue in this wave. Uniqueness is
# per-table, so nothing stops two tables from minting the same value; a shared
# UUID would break the eventual cross-model identity lookups these columns
# exist for.
CONVERTED_MODELS = (
    "Game",
    "Platform",
    "Session",
    "PlayEvent",
    "GameStatusChange",
    "Purchase",
)


def require_match(path, actual, expected):
    if actual != expected:
        raise RuntimeError(f"LIB identity {path} mismatch: {actual!r} != {expected!r}")


def floor_ms(moment):
    elapsed = moment - _EPOCH
    return (
        elapsed.days * 86_400_000
        + elapsed.seconds * 1000
        + elapsed.microseconds // 1000
    )


def backfill_model_uuids(model):
    updated = []
    previous_ms = None
    sequence = 0
    rows = model.objects.order_by("created_at", "pk").only("pk", "created_at")
    for row in rows:
        current_ms = floor_ms(row.created_at)
        sequence = sequence + 1 if current_ms == previous_ms else 0
        previous_ms = current_ms
        row.uuid = uuid7_at(row.created_at, sequence=sequence)
        updated.append(row)
    model.objects.bulk_update(updated, ["uuid"], batch_size=1000)


def model_identity_counts(table_name):
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT
                count(*),
                count(DISTINCT uuid),
                count(*) FILTER (WHERE uuid IS NULL),
                count(*) FILTER (
                    WHERE uuid_extract_version(uuid) IS DISTINCT FROM 7
                ),
                coalesce(max(abs(extract(epoch FROM (
                    uuid_extract_timestamp(uuid)
                    - date_trunc('milliseconds', created_at)
                )) * 1000)), 0)
            FROM "{table_name}"
            """
        )
        return cursor.fetchone()


def order_preserved(model):
    by_uuid = list(model.objects.order_by("uuid").values_list("pk", flat=True))
    by_created = list(
        model.objects.order_by("created_at", "pk").values_list("pk", flat=True)
    )
    return by_uuid == by_created


def reconcile_model_identity(model, label):
    expected_rows = model.objects.count()
    (
        row_count,
        distinct_count,
        null_count,
        bad_version_count,
        max_delta_ms,
    ) = model_identity_counts(model._meta.db_table)

    require_match(f"{label}.row_count", row_count, expected_rows)
    require_match(f"{label}.null_count", null_count, 0)
    require_match(f"{label}.distinct_count", distinct_count, expected_rows)
    require_match(f"{label}.bad_version_count", bad_version_count, 0)
    require_match(f"{label}.max_timestamp_delta_ms", max_delta_ms, 0)
    require_match(f"{label}.order_preserved", order_preserved(model), True)
    return expected_rows


def reconcile_library_config_identity(apps):
    Device = apps.get_model("games", "Device")
    FilterPreset = apps.get_model("games", "FilterPreset")

    device_rows = reconcile_model_identity(Device, "Device")
    filterpreset_rows = reconcile_model_identity(FilterPreset, "FilterPreset")

    per_model_uuids = [
        set(model.objects.values_list("uuid", flat=True))
        for model in (Device, FilterPreset)
    ]
    per_model_uuids += [
        set(apps.get_model("games", name).objects.values_list("uuid", flat=True))
        for name in CONVERTED_MODELS
    ]
    combined = set().union(*per_model_uuids)
    require_match(
        "cross_model.shared_uuid_count",
        sum(len(uuids) for uuids in per_model_uuids) - len(combined),
        0,
    )

    print(
        "LIB identity backfilled "
        f"device_rows={device_rows} device_distinct={device_rows} "
        f"filterpreset_rows={filterpreset_rows} "
        f"filterpreset_distinct={filterpreset_rows} "
        "max_timestamp_delta_ms=0 order_preserved=true"
    )


def backfill_library_config_uuids(apps, schema_editor):
    del schema_editor
    backfill_model_uuids(apps.get_model("games", "Device"))
    backfill_model_uuids(apps.get_model("games", "FilterPreset"))
    reconcile_library_config_identity(apps)


class Migration(migrations.Migration):
    dependencies = [
        ("games", "0007_purchase_uuid_identity"),
    ]

    operations = [
        migrations.AddField(
            model_name="device",
            name="uuid",
            field=UUIDv7Field(null=True, default=None, db_default=None, editable=False),
        ),
        migrations.AddField(
            model_name="filterpreset",
            name="uuid",
            field=UUIDv7Field(null=True, default=None, db_default=None, editable=False),
        ),
        migrations.RunPython(backfill_library_config_uuids, migrations.RunPython.noop),
        # Every FK in this schema is DEFERRABLE INITIALLY DEFERRED (see 0004's
        # identical use of this statement). If any row referencing these tables
        # was inserted earlier in this same transaction, its deferred RI check
        # is still pending and blocks the ALTER TABLEs below with "cannot ALTER
        # TABLE because it has pending trigger events" - force it to resolve
        # now instead.
        migrations.RunSQL(
            sql="SET CONSTRAINTS ALL IMMEDIATE",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.AlterField(
            model_name="device",
            name="uuid",
            field=UUIDv7Field(unique=True, editable=False),
        ),
        migrations.AlterField(
            model_name="filterpreset",
            name="uuid",
            field=UUIDv7Field(unique=True, editable=False),
        ),
    ]
