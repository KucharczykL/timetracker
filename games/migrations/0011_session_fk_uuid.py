import django.db.models.deletion
from django.db import migrations, models

from timetracker.uuidv7 import UUIDv7Field


def require_match(path, actual, expected):
    if actual != expected:
        raise RuntimeError(f"FK identity {path} mismatch: {actual!r} != {expected!r}")


def backfill(cursor, table_name, column, target_table):
    cursor.execute(
        f"""
        UPDATE "{table_name}" AS child
        SET {column}_uuid = target.uuid
        FROM {target_table} AS target
        WHERE target.id = child.{column}_id
        """
    )


def restore(cursor, table_name, column, target_table):
    cursor.execute(
        f"""
        UPDATE "{table_name}" AS child
        SET {column}_id = target.id
        FROM {target_table} AS target
        WHERE target.uuid = child.{column}_uuid
        """
    )


def reconcile(cursor, table_name, column, target_table, label, *, nullable):
    """Verify one relation's backfill, raising on any mismatch.

    For a nullable relation the invariant is not "no NULLs remain" but "the NULL
    set is unchanged" - asserted as two zero-row anti-joins rather than a count
    comparison, which would pass if one row gained NULL while another lost it.
    Rows with no target match no join row and are left untouched by the
    backfill, which is what makes both directions total.
    """
    if nullable:
        cursor.execute(
            f"""
            SELECT count(*) FROM "{table_name}"
            WHERE {column}_id IS NULL AND {column}_uuid IS NOT NULL
            """
        )
        (invented,) = cursor.fetchone()
        require_match(f"{label}.invented_from_null", invented, 0)

    cursor.execute(
        f"""
        SELECT count(*) FROM "{table_name}"
        WHERE {column}_id IS NOT NULL AND {column}_uuid IS NULL
        """
    )
    (lost,) = cursor.fetchone()
    require_match(f"{label}.lost_to_null", lost, 0)

    cursor.execute(
        f"""
        SELECT count(*)
        FROM "{table_name}" AS child
        JOIN {target_table} AS target ON target.id = child.{column}_id
        WHERE child.{column}_uuid IS DISTINCT FROM target.uuid
        """
    )
    (unmatched_count,) = cursor.fetchone()
    require_match(f"{label}.unmatched_count", unmatched_count, 0)

    cursor.execute(f'SELECT count(*) FROM "{table_name}"')
    (row_count,) = cursor.fetchone()

    cursor.execute(f'SELECT count(*) FROM "{table_name}" WHERE {column}_uuid IS NULL')
    (null_count,) = cursor.fetchone()
    if not nullable:
        require_match(f"{label}.null_count", null_count, 0)

    cursor.execute(f'SELECT count(DISTINCT {column}_id) FROM "{table_name}"')
    (targets_before,) = cursor.fetchone()
    cursor.execute(f'SELECT count(DISTINCT {column}_uuid) FROM "{table_name}"')
    (targets_after,) = cursor.fetchone()
    require_match(f"{label}.distinct_target_count", targets_after, targets_before)

    return row_count, targets_after, null_count


def fill_uuid_from_integer(apps, schema_editor):
    del apps
    with schema_editor.connection.cursor() as cursor:
        backfill(cursor, "games_session", "game", "games_game")
        backfill(cursor, "games_session", "device", "games_device")
        backfill(
            cursor, "games_userlibrarypreferences", "default_device", "games_device"
        )

        session_rows, session_games, _ = reconcile(
            cursor,
            "games_session",
            "game",
            "games_game",
            "Session.game",
            nullable=False,
        )
        _, session_devices, session_device_nulls = reconcile(
            cursor,
            "games_session",
            "device",
            "games_device",
            "Session.device",
            nullable=True,
        )
        preferences_rows, preferences_devices, preferences_device_nulls = reconcile(
            cursor,
            "games_userlibrarypreferences",
            "default_device",
            "games_device",
            "UserLibraryPreferences.default_device",
            nullable=True,
        )

    print(
        "FK identity rewritten "
        f"session_rows={session_rows} session_games={session_games} "
        f"session_devices={session_devices} "
        f"session_device_nulls={session_device_nulls} "
        f"preferences_rows={preferences_rows} "
        f"preferences_devices={preferences_devices} "
        f"preferences_device_nulls={preferences_device_nulls} unmatched=0"
    )


def fill_integer_from_uuid(apps, schema_editor):
    del apps
    with schema_editor.connection.cursor() as cursor:
        restore(cursor, "games_session", "game", "games_game")
        restore(cursor, "games_session", "device", "games_device")
        restore(
            cursor, "games_userlibrarypreferences", "default_device", "games_device"
        )


class Migration(migrations.Migration):
    dependencies = [
        ("games", "0010_platform_fk_uuid"),
    ]

    operations = [
        # Step 1 (Session.game only): relax NOT NULL now, so the reverse
        # direction can re-impose it last, after the reverse backfill has
        # refilled the column. The two nullable relations need no counterpart -
        # there is no constraint to relax, and implying one would be a lie.
        migrations.AlterField(
            model_name="session",
            name="game",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="sessions",
                to="games.game",
            ),
        ),
        # Step 2 (all three): an empty holding column for the backfilled UUID,
        # added the way 0005/0006/0009/0010 add a uuid column - explicit Nones
        # suppress UUIDv7Field's own defaults.
        migrations.AddField(
            model_name="session",
            name="game_uuid",
            field=UUIDv7Field(null=True, default=None, db_default=None, editable=False),
        ),
        migrations.AddField(
            model_name="session",
            name="device_uuid",
            field=UUIDv7Field(null=True, default=None, db_default=None, editable=False),
        ),
        migrations.AddField(
            model_name="userlibrarypreferences",
            name="default_device_uuid",
            field=UUIDv7Field(null=True, default=None, db_default=None, editable=False),
        ),
        # Step 3: backfill + reconciliation for all three relations.
        migrations.RunPython(fill_uuid_from_integer, fill_integer_from_uuid),
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
        # Steps 4-6 (Session.game): drop the integer column, rename the UUID
        # holding column into its place, then retype it into the real FK -
        # renaming the column to `game_id`, setting NOT NULL, and creating the
        # FK constraint and index.
        migrations.RemoveField(
            model_name="session",
            name="game",
        ),
        migrations.RenameField(
            model_name="session",
            old_name="game_uuid",
            new_name="game",
        ),
        migrations.AlterField(
            model_name="session",
            name="game",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="sessions",
                to="games.game",
                to_field="uuid",
            ),
        ),
        # Steps 4-6 (Session.device): same shape, staying nullable throughout.
        migrations.RemoveField(
            model_name="session",
            name="device",
        ),
        migrations.RenameField(
            model_name="session",
            old_name="device_uuid",
            new_name="device",
        ),
        migrations.AlterField(
            model_name="session",
            name="device",
            field=models.ForeignKey(
                blank=True,
                default=None,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to="games.device",
                to_field="uuid",
            ),
        ),
        # Steps 4-6 (UserLibraryPreferences.default_device): the fourth Device
        # foreign key, taken here so ID-14 promotes Device.uuid to primary key
        # with no integer foreign key left pointing at it.
        migrations.RemoveField(
            model_name="userlibrarypreferences",
            name="default_device",
        ),
        migrations.RenameField(
            model_name="userlibrarypreferences",
            old_name="default_device_uuid",
            new_name="default_device",
        ),
        migrations.AlterField(
            model_name="userlibrarypreferences",
            name="default_device",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="games.device",
                to_field="uuid",
            ),
        ),
    ]
