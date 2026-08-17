from datetime import UTC, datetime

from django.db import connection, migrations

from timetracker.uuidv7 import UUIDv7Field, uuid7_at

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def require_match(path, actual, expected):
    if actual != expected:
        raise RuntimeError(f"CAT identity {path} mismatch: {actual!r} != {expected!r}")


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


def reconcile_catalog_identity(apps):
    Game = apps.get_model("games", "Game")
    Platform = apps.get_model("games", "Platform")

    game_rows = Game.objects.count()
    platform_rows = Platform.objects.count()

    (
        game_row_count,
        game_distinct,
        game_null,
        game_bad_version,
        game_max_delta_ms,
    ) = model_identity_counts(Game._meta.db_table)
    (
        platform_row_count,
        platform_distinct,
        platform_null,
        platform_bad_version,
        platform_max_delta_ms,
    ) = model_identity_counts(Platform._meta.db_table)

    require_match("Game.row_count", game_row_count, game_rows)
    require_match("Game.null_count", game_null, 0)
    require_match("Game.distinct_count", game_distinct, game_rows)
    require_match("Game.bad_version_count", game_bad_version, 0)
    require_match("Game.max_timestamp_delta_ms", game_max_delta_ms, 0)

    require_match("Platform.row_count", platform_row_count, platform_rows)
    require_match("Platform.null_count", platform_null, 0)
    require_match("Platform.distinct_count", platform_distinct, platform_rows)
    require_match("Platform.bad_version_count", platform_bad_version, 0)
    require_match("Platform.max_timestamp_delta_ms", platform_max_delta_ms, 0)

    shared_uuids = set(Game.objects.values_list("uuid", flat=True)) & set(
        Platform.objects.values_list("uuid", flat=True)
    )
    require_match("cross_model.shared_uuid_count", len(shared_uuids), 0)

    require_match("Game.order_preserved", order_preserved(Game), True)
    require_match("Platform.order_preserved", order_preserved(Platform), True)

    print(
        "CAT identity backfilled "
        f"game_rows={game_rows} game_distinct={game_distinct} "
        f"platform_rows={platform_rows} platform_distinct={platform_distinct} "
        "max_timestamp_delta_ms=0 order_preserved=true"
    )


def backfill_catalog_uuids(apps, schema_editor):
    del schema_editor
    Game = apps.get_model("games", "Game")
    Platform = apps.get_model("games", "Platform")
    backfill_model_uuids(Game)
    backfill_model_uuids(Platform)
    reconcile_catalog_identity(apps)


class Migration(migrations.Migration):
    dependencies = [
        ("games", "0004_user_library_ownership_cutover"),
    ]

    operations = [
        migrations.AddField(
            model_name="game",
            name="uuid",
            field=UUIDv7Field(null=True, default=None, db_default=None, editable=False),
        ),
        migrations.AddField(
            model_name="platform",
            name="uuid",
            field=UUIDv7Field(null=True, default=None, db_default=None, editable=False),
        ),
        migrations.RunPython(backfill_catalog_uuids, migrations.RunPython.noop),
        # Every FK in this schema is DEFERRABLE INITIALLY DEFERRED (see
        # 0004's identical use of this statement). If any row referencing
        # game/platform was inserted earlier in this same transaction, its
        # deferred RI check is still pending and blocks the ALTER TABLEs
        # below with "cannot ALTER TABLE because it has pending trigger
        # events" - force it to resolve now instead.
        migrations.RunSQL(
            sql="SET CONSTRAINTS ALL IMMEDIATE",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.AlterField(
            model_name="game",
            name="uuid",
            field=UUIDv7Field(unique=True, editable=False),
        ),
        migrations.AlterField(
            model_name="platform",
            name="uuid",
            field=UUIDv7Field(unique=True, editable=False),
        ),
    ]
