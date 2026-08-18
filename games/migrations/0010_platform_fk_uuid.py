import django.db.models.deletion
from django.db import migrations, models

from timetracker.uuidv7 import UUIDv7Field


def require_match(path, actual, expected):
    if actual != expected:
        raise RuntimeError(f"FK identity {path} mismatch: {actual!r} != {expected!r}")


def backfill_platform_uuid(cursor, table_name):
    cursor.execute(
        f"""
        UPDATE "{table_name}" AS child
        SET platform_uuid = platform.uuid
        FROM games_platform AS platform
        WHERE platform.id = child.platform_id
        """
    )


def restore_platform_id(cursor, table_name):
    cursor.execute(
        f"""
        UPDATE "{table_name}" AS child
        SET platform_id = platform.id
        FROM games_platform AS platform
        WHERE platform.uuid = child.platform_uuid
        """
    )


def reconcile_platform_uuid(cursor, table_name, label):
    """Verify the backfill for one table, raising on any mismatch.

    The relation is nullable, so the invariant is not "no NULLs remain" but
    "the NULL set is unchanged" — asserted as two zero-row anti-joins rather
    than a count comparison, which would pass if one row gained NULL while
    another lost it. Rows with no platform match no join row and are left
    untouched by the backfill, which is what makes both directions total.
    """
    cursor.execute(
        f"""
        SELECT count(*) FROM "{table_name}"
        WHERE platform_id IS NULL AND platform_uuid IS NOT NULL
        """
    )
    (invented,) = cursor.fetchone()
    require_match(f"{label}.invented_from_null", invented, 0)

    cursor.execute(
        f"""
        SELECT count(*) FROM "{table_name}"
        WHERE platform_id IS NOT NULL AND platform_uuid IS NULL
        """
    )
    (lost,) = cursor.fetchone()
    require_match(f"{label}.lost_to_null", lost, 0)

    cursor.execute(
        f"""
        SELECT count(*)
        FROM "{table_name}" AS child
        JOIN games_platform AS platform ON platform.id = child.platform_id
        WHERE child.platform_uuid IS DISTINCT FROM platform.uuid
        """
    )
    (unmatched_count,) = cursor.fetchone()
    require_match(f"{label}.unmatched_count", unmatched_count, 0)

    cursor.execute(f'SELECT count(*) FROM "{table_name}"')
    (row_count,) = cursor.fetchone()

    cursor.execute(f'SELECT count(*) FROM "{table_name}" WHERE platform_uuid IS NULL')
    (null_count,) = cursor.fetchone()

    cursor.execute(f'SELECT count(DISTINCT platform_id) FROM "{table_name}"')
    (platforms_before,) = cursor.fetchone()
    cursor.execute(f'SELECT count(DISTINCT platform_uuid) FROM "{table_name}"')
    (platforms_after,) = cursor.fetchone()
    require_match(f"{label}.distinct_platform_count", platforms_after, platforms_before)

    return row_count, platforms_after, null_count


def fill_uuid_from_integer(apps, schema_editor):
    del apps
    with schema_editor.connection.cursor() as cursor:
        backfill_platform_uuid(cursor, "games_game")
        backfill_platform_uuid(cursor, "games_purchase")

        game_rows, game_platforms, game_nulls = reconcile_platform_uuid(
            cursor, "games_game", "Game"
        )
        purchase_rows, purchase_platforms, purchase_nulls = reconcile_platform_uuid(
            cursor, "games_purchase", "Purchase"
        )

    print(
        "FK identity rewritten "
        f"game_rows={game_rows} game_platforms={game_platforms} "
        f"game_nulls={game_nulls} "
        f"purchase_rows={purchase_rows} purchase_platforms={purchase_platforms} "
        f"purchase_nulls={purchase_nulls} unmatched=0"
    )


def fill_integer_from_uuid(apps, schema_editor):
    del apps
    with schema_editor.connection.cursor() as cursor:
        restore_platform_id(cursor, "games_game")
        restore_platform_id(cursor, "games_purchase")


class Migration(migrations.Migration):
    dependencies = [
        ("games", "0009_playhistory_game_uuid_fk"),
    ]

    operations = [
        # Game's two uniqueness guarantees are built on the column about to be
        # dropped. RemoveField compiles to a bare DROP COLUMN, and PostgreSQL
        # cascades away every index over that column - while Django's migration
        # state still lists both, so the state-based drift guard would report
        # nothing. Take them down explicitly here and put them back after the
        # swap. The unique_together also names the `platform` *field*, so it
        # cannot stay declared across the window where that field is absent.
        migrations.AlterUniqueTogether(
            name="game",
            unique_together=set(),
        ),
        migrations.RemoveConstraint(
            model_name="game",
            name="unique_library_platformless_game_name_year",
        ),
        # Step 1 (both models): an empty holding column for the backfilled
        # UUID, added the way 0005/0006/0009 add a uuid column - explicit Nones
        # suppress UUIDv7Field's own defaults.
        #
        # ID-06's leading AlterField has no counterpart here: it existed to
        # relax a NOT NULL so the reverse direction could re-impose it last,
        # and both of these columns are nullable before and after.
        migrations.AddField(
            model_name="game",
            name="platform_uuid",
            field=UUIDv7Field(null=True, default=None, db_default=None, editable=False),
        ),
        migrations.AddField(
            model_name="purchase",
            name="platform_uuid",
            field=UUIDv7Field(null=True, default=None, db_default=None, editable=False),
        ),
        # Step 2: backfill + reconciliation for both models.
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
        # Steps 3-5 (Game): drop the integer column, rename the UUID holding
        # column into its place, then retype it into the real FK - renaming the
        # column to `platform_id` and creating the FK constraint and index.
        migrations.RemoveField(
            model_name="game",
            name="platform",
        ),
        migrations.RenameField(
            model_name="game",
            old_name="platform_uuid",
            new_name="platform",
        ),
        migrations.AlterField(
            model_name="game",
            name="platform",
            field=models.ForeignKey(
                blank=True,
                default=None,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to="games.platform",
                to_field="uuid",
            ),
        ),
        # Steps 3-5 (Purchase): same shape.
        migrations.RemoveField(
            model_name="purchase",
            name="platform",
        ),
        migrations.RenameField(
            model_name="purchase",
            old_name="platform_uuid",
            new_name="platform",
        ),
        migrations.AlterField(
            model_name="purchase",
            name="platform",
            field=models.ForeignKey(
                blank=True,
                default=None,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to="games.platform",
                to_field="uuid",
            ),
        ),
        # Both guarantees restored over the new column.
        migrations.AddConstraint(
            model_name="game",
            constraint=models.UniqueConstraint(
                condition=models.Q(("platform__isnull", True)),
                fields=("library", "name", "year_released"),
                name="unique_library_platformless_game_name_year",
            ),
        ),
        migrations.AlterUniqueTogether(
            name="game",
            unique_together={("library", "name", "platform", "year_released")},
        ),
    ]
