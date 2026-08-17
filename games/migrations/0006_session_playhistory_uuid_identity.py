from datetime import UTC, datetime

from django.db import connection, migrations
from django.utils import timezone

from timetracker.uuidv7 import UUIDv7Field, uuid7_at

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def require_match(path, actual, expected):
    if actual != expected:
        raise RuntimeError(f"SES identity {path} mismatch: {actual!r} != {expected!r}")


def floor_ms(moment):
    elapsed = moment - _EPOCH
    return (
        elapsed.days * 86_400_000
        + elapsed.seconds * 1000
        + elapsed.microseconds // 1000
    )


def backfill_model_uuids(model, source_field, *, fallback_moment):
    updated = []
    previous_ms = None
    sequence = 0
    rows = model.objects.order_by(source_field, "pk").only("pk", source_field)
    for row in rows:
        moment = getattr(row, source_field)
        if moment is None:
            # PostgreSQL's default ASC ordering is NULLS LAST, so these rows
            # are the tail of the iteration: stamping them with the migration's
            # own clock keeps them after every historical row. They carry no
            # order relative to each other, so no sequence is assigned.
            row.uuid = uuid7_at(fallback_moment)
        else:
            current_ms = floor_ms(moment)
            sequence = sequence + 1 if current_ms == previous_ms else 0
            previous_ms = current_ms
            row.uuid = uuid7_at(moment, sequence=sequence)
        updated.append(row)
    model.objects.bulk_update(updated, ["uuid"], batch_size=1000)


def model_identity_counts(table_name, source_column):
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
                count(*) FILTER (WHERE {source_column} IS NULL),
                coalesce(max(abs(extract(epoch FROM (
                    uuid_extract_timestamp(uuid)
                    - date_trunc('milliseconds', {source_column})
                )) * 1000)) FILTER (WHERE {source_column} IS NOT NULL), 0)
            FROM "{table_name}"
            """
        )
        return cursor.fetchone()


def order_preserved(model, source_field):
    """Whether `order_by("uuid")` reproduces `order_by(source_field, "pk")`.

    Rows with a NULL source value are excluded: they were assigned unsequenced
    migration-time UUIDs, so they hold no order among themselves -
    `null_rows_sort_last` covers them instead.
    """
    rows = model.objects.filter(**{f"{source_field}__isnull": False})
    by_uuid = list(rows.order_by("uuid").values_list("pk", flat=True))
    by_source = list(rows.order_by(source_field, "pk").values_list("pk", flat=True))
    return by_uuid == by_source


def null_rows_sort_last(model, source_field):
    null_pks = set(
        model.objects.filter(**{f"{source_field}__isnull": True}).values_list(
            "pk", flat=True
        )
    )
    if not null_pks:
        return True
    by_uuid = list(model.objects.order_by("uuid").values_list("pk", flat=True))
    return set(by_uuid[-len(null_pks) :]) == null_pks


def reconcile_model_identity(model, label, source_field):
    expected_rows = model.objects.count()
    (
        row_count,
        distinct_count,
        null_uuid_count,
        bad_version_count,
        null_source_count,
        max_delta_ms,
    ) = model_identity_counts(model._meta.db_table, source_field)

    require_match(f"{label}.row_count", row_count, expected_rows)
    require_match(f"{label}.null_count", null_uuid_count, 0)
    require_match(f"{label}.distinct_count", distinct_count, expected_rows)
    require_match(f"{label}.bad_version_count", bad_version_count, 0)
    require_match(f"{label}.max_timestamp_delta_ms", max_delta_ms, 0)
    require_match(
        f"{label}.order_preserved", order_preserved(model, source_field), True
    )
    require_match(
        f"{label}.null_rows_sort_last", null_rows_sort_last(model, source_field), True
    )
    return expected_rows, null_source_count


def reconcile_playhistory_identity(apps):
    Session = apps.get_model("games", "Session")
    PlayEvent = apps.get_model("games", "PlayEvent")
    GameStatusChange = apps.get_model("games", "GameStatusChange")

    session_rows, _ = reconcile_model_identity(Session, "Session", "created_at")
    playevent_rows, _ = reconcile_model_identity(PlayEvent, "PlayEvent", "created_at")
    gamestatuschange_rows, gamestatuschange_null_timestamps = reconcile_model_identity(
        GameStatusChange, "GameStatusChange", "timestamp"
    )

    # Uniqueness is per-table, so nothing stops two tables from minting the
    # same value; a shared UUID would break the eventual cross-model identity
    # lookups these columns exist for.
    Game = apps.get_model("games", "Game")
    Platform = apps.get_model("games", "Platform")
    per_model_uuids = [
        set(model.objects.values_list("uuid", flat=True))
        for model in (Session, PlayEvent, GameStatusChange, Game, Platform)
    ]
    combined = set().union(*per_model_uuids)
    require_match(
        "cross_model.shared_uuid_count",
        sum(len(uuids) for uuids in per_model_uuids) - len(combined),
        0,
    )

    print(
        "SES identity backfilled "
        f"session_rows={session_rows} "
        f"playevent_rows={playevent_rows} "
        f"gamestatuschange_rows={gamestatuschange_rows} "
        f"gamestatuschange_null_timestamp_rows={gamestatuschange_null_timestamps} "
        "max_timestamp_delta_ms=0 order_preserved=true"
    )


def backfill_playhistory_uuids(apps, schema_editor):
    del schema_editor
    Session = apps.get_model("games", "Session")
    PlayEvent = apps.get_model("games", "PlayEvent")
    GameStatusChange = apps.get_model("games", "GameStatusChange")
    fallback_moment = timezone.now()
    backfill_model_uuids(Session, "created_at", fallback_moment=fallback_moment)
    backfill_model_uuids(PlayEvent, "created_at", fallback_moment=fallback_moment)
    backfill_model_uuids(GameStatusChange, "timestamp", fallback_moment=fallback_moment)
    reconcile_playhistory_identity(apps)


class Migration(migrations.Migration):
    dependencies = [
        ("games", "0005_catalog_uuid_identity"),
    ]

    operations = [
        migrations.AddField(
            model_name="session",
            name="uuid",
            field=UUIDv7Field(null=True, default=None, db_default=None, editable=False),
        ),
        migrations.AddField(
            model_name="playevent",
            name="uuid",
            field=UUIDv7Field(null=True, default=None, db_default=None, editable=False),
        ),
        migrations.AddField(
            model_name="gamestatuschange",
            name="uuid",
            field=UUIDv7Field(null=True, default=None, db_default=None, editable=False),
        ),
        migrations.RunPython(backfill_playhistory_uuids, migrations.RunPython.noop),
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
            model_name="session",
            name="uuid",
            field=UUIDv7Field(unique=True, editable=False),
        ),
        migrations.AlterField(
            model_name="playevent",
            name="uuid",
            field=UUIDv7Field(unique=True, editable=False),
        ),
        migrations.AlterField(
            model_name="gamestatuschange",
            name="uuid",
            field=UUIDv7Field(unique=True, editable=False),
        ),
    ]
