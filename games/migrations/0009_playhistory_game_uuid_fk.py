import django.db.models.deletion
from django.db import migrations, models

from timetracker.uuidv7 import UUIDv7Field


def require_match(path, actual, expected):
    if actual != expected:
        raise RuntimeError(f"FK identity {path} mismatch: {actual!r} != {expected!r}")


def backfill_game_uuid(cursor, table_name):
    cursor.execute(
        f"""
        UPDATE "{table_name}" AS child
        SET game_uuid = game.uuid
        FROM games_game AS game
        WHERE game.id = child.game_id
        """
    )


def restore_game_id(cursor, table_name):
    cursor.execute(
        f"""
        UPDATE "{table_name}" AS child
        SET game_id = game.id
        FROM games_game AS game
        WHERE game.uuid = child.game_uuid
        """
    )


def reconcile_game_uuid(cursor, table_name, label):
    """Verify the backfill for one table, raising on any mismatch.

    The anti-join is a zero-row check, not a count comparison: it fails on any
    single row whose backfilled `game_uuid` disagrees with the `Game` its
    original integer `game_id` pointed at, even if the aggregate counts happen
    to still line up.
    """
    cursor.execute(f'SELECT count(*) FROM "{table_name}" WHERE game_uuid IS NULL')
    (null_count,) = cursor.fetchone()
    require_match(f"{label}.null_count", null_count, 0)

    cursor.execute(
        f"""
        SELECT count(*)
        FROM "{table_name}" AS child
        JOIN games_game AS game ON game.id = child.game_id
        WHERE child.game_uuid IS DISTINCT FROM game.uuid
        """
    )
    (unmatched_count,) = cursor.fetchone()
    require_match(f"{label}.unmatched_count", unmatched_count, 0)

    cursor.execute(f'SELECT count(*) FROM "{table_name}"')
    (row_count,) = cursor.fetchone()

    cursor.execute(f'SELECT count(DISTINCT game_id) FROM "{table_name}"')
    (games_before,) = cursor.fetchone()
    cursor.execute(f'SELECT count(DISTINCT game_uuid) FROM "{table_name}"')
    (games_after,) = cursor.fetchone()
    require_match(f"{label}.distinct_game_count", games_after, games_before)

    return row_count, games_after


def fill_uuid_from_integer(apps, schema_editor):
    del apps
    with schema_editor.connection.cursor() as cursor:
        backfill_game_uuid(cursor, "games_playevent")
        backfill_game_uuid(cursor, "games_gamestatuschange")

        playevent_rows, playevent_games = reconcile_game_uuid(
            cursor, "games_playevent", "PlayEvent"
        )
        gamestatuschange_rows, gamestatuschange_games = reconcile_game_uuid(
            cursor, "games_gamestatuschange", "GameStatusChange"
        )

    print(
        "FK identity rewritten "
        f"playevent_rows={playevent_rows} playevent_games={playevent_games} "
        f"gamestatuschange_rows={gamestatuschange_rows} "
        f"gamestatuschange_games={gamestatuschange_games} unmatched=0"
    )


def fill_integer_from_uuid(apps, schema_editor):
    del apps
    with schema_editor.connection.cursor() as cursor:
        restore_game_id(cursor, "games_playevent")
        restore_game_id(cursor, "games_gamestatuschange")


class Migration(migrations.Migration):
    dependencies = [
        ("games", "0008_library_config_uuid_identity"),
    ]

    operations = [
        # Step 1 (both models): relax NOT NULL now, so the reverse direction
        # can re-impose it last, after the reverse backfill has refilled the
        # column.
        migrations.AlterField(
            model_name="playevent",
            name="game",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="playevents",
                to="games.game",
            ),
        ),
        migrations.AlterField(
            model_name="gamestatuschange",
            name="game",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="status_changes",
                to="games.game",
            ),
        ),
        # Step 2 (both models): an empty holding column for the backfilled
        # UUID, added the same way 0005/0006 add a uuid column - explicit
        # Nones suppress UUIDv7Field's own defaults.
        migrations.AddField(
            model_name="playevent",
            name="game_uuid",
            field=UUIDv7Field(null=True, default=None, db_default=None, editable=False),
        ),
        migrations.AddField(
            model_name="gamestatuschange",
            name="game_uuid",
            field=UUIDv7Field(null=True, default=None, db_default=None, editable=False),
        ),
        # Step 3: backfill + reconciliation for both models.
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
        # Steps 4-6 (PlayEvent): drop the integer column, rename the UUID
        # holding column into its place, then retype it into the real FK -
        # renaming the column to `game_id`, setting NOT NULL, and creating
        # the FK constraint and index.
        migrations.RemoveField(
            model_name="playevent",
            name="game",
        ),
        migrations.RenameField(
            model_name="playevent",
            old_name="game_uuid",
            new_name="game",
        ),
        migrations.AlterField(
            model_name="playevent",
            name="game",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="playevents",
                to="games.game",
                to_field="uuid",
            ),
        ),
        # Steps 4-6 (GameStatusChange): same shape.
        migrations.RemoveField(
            model_name="gamestatuschange",
            name="game",
        ),
        migrations.RenameField(
            model_name="gamestatuschange",
            old_name="game_uuid",
            new_name="game",
        ),
        migrations.AlterField(
            model_name="gamestatuschange",
            name="game",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="status_changes",
                to="games.game",
                to_field="uuid",
            ),
        ),
    ]
