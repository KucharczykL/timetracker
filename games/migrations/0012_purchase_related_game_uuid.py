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
        backfill(cursor, "games_purchase", "related_game", "games_game")
        rows, related_games, nulls = reconcile(
            cursor,
            "games_purchase",
            "related_game",
            "games_game",
            "Purchase.related_game",
            nullable=True,
        )

    print(
        "FK identity rewritten "
        f"purchase_rows={rows} purchase_related_games={related_games} "
        f"purchase_related_game_nulls={nulls} unmatched=0"
    )


def fill_integer_from_uuid(apps, schema_editor):
    del apps
    with schema_editor.connection.cursor() as cursor:
        restore(cursor, "games_purchase", "related_game", "games_game")


class Migration(migrations.Migration):
    dependencies = [
        ("games", "0011_session_fk_uuid"),
    ]

    operations = [
        # Step 1: an empty holding column for the backfilled UUID, added the way
        # 0005/0006/0009/0010/0011 add a uuid column - explicit Nones suppress
        # UUIDv7Field's own defaults. ID-06's leading AlterField has no
        # counterpart here: it exists only to relax a NOT NULL, and this column
        # is already nullable.
        migrations.AddField(
            model_name="purchase",
            name="related_game_uuid",
            field=UUIDv7Field(null=True, default=None, db_default=None, editable=False),
        ),
        # Step 2: backfill + reconciliation.
        migrations.RunPython(fill_uuid_from_integer, fill_integer_from_uuid),
        # Every FK in this schema is DEFERRABLE INITIALLY DEFERRED (see 0004's
        # identical use of this statement). If any row referencing this table
        # was inserted earlier in this same transaction, its deferred RI check
        # is still pending and blocks the ALTER TABLEs below with "cannot ALTER
        # TABLE because it has pending trigger events" - force it to resolve
        # now instead.
        migrations.RunSQL(
            sql="SET CONSTRAINTS ALL IMMEDIATE",
            reverse_sql=migrations.RunSQL.noop,
        ),
        # Steps 3-5: drop the integer column, rename the UUID holding column
        # into its place, then retype it into the real FK - renaming the column
        # to `related_game_id` and creating the FK constraint and index.
        migrations.RemoveField(
            model_name="purchase",
            name="related_game",
        ),
        migrations.RenameField(
            model_name="purchase",
            old_name="related_game_uuid",
            new_name="related_game",
        ),
        migrations.AlterField(
            model_name="purchase",
            name="related_game",
            field=models.ForeignKey(
                blank=True,
                default=None,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="addon_purchases",
                to="games.game",
                to_field="uuid",
                verbose_name="Base game",
            ),
        ),
    ]
