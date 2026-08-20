from django.db import migrations

from timetracker.uuidv7 import UUIDv7Field

THROUGH_TABLE = "games_purchase_games"
PURCHASE_TABLE = "games_purchase"
FK_SUFFIX = "_fk_%(to_table)s_%(to_column)s"


def promote_state():
    return [
        migrations.RemoveField(model_name="purchase", name="id"),
        migrations.RemoveField(model_name="purchase", name="uuid"),
        migrations.AddField(
            model_name="purchase",
            name="id",
            field=UUIDv7Field(
                primary_key=True,
                editable=False,
                serialize=False,
            ),
        ),
    ]


def _drop_redundant_unique_constraint(cursor):
    cursor.execute(
        """
        SELECT conname FROM pg_constraint
        WHERE conrelid = %s::regclass AND contype = 'u'
          AND pg_get_constraintdef(oid) = 'UNIQUE (id)'
        """,
        [PURCHASE_TABLE],
    )
    for (constraint_name,) in cursor.fetchall():
        cursor.execute(
            f'ALTER TABLE "{PURCHASE_TABLE}" DROP CONSTRAINT "{constraint_name}"'
        )


def _create_through_constraints(apps, schema_editor):
    through = apps.get_model("games", "Purchase").games.through
    purchase_field = through._meta.get_field("purchase")
    schema_editor.execute(
        schema_editor._create_fk_sql(through, purchase_field, FK_SUFFIX)
    )
    schema_editor.execute(
        schema_editor._create_index_sql(through, fields=[purchase_field])
    )
    schema_editor.alter_unique_together(through, [], [("purchase", "game")])


def promote_purchase_identity(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            f'ALTER TABLE "{THROUGH_TABLE}" ADD COLUMN purchase_uuid uuid_v7'
        )
        cursor.execute(f'SELECT count(*) FROM "{THROUGH_TABLE}"')
        (through_rows_before,) = cursor.fetchone()
        cursor.execute(
            f"""
            UPDATE "{THROUGH_TABLE}" AS through
            SET purchase_uuid = target.uuid
            FROM "{PURCHASE_TABLE}" AS target
            WHERE target.id = through.purchase_id
            """
        )
        cursor.execute(
            f'SELECT count(*) FROM "{THROUGH_TABLE}" WHERE purchase_uuid IS NULL'
        )
        (unmatched,) = cursor.fetchone()
        cursor.execute(f'SELECT count(DISTINCT purchase_id) FROM "{THROUGH_TABLE}"')
        (linked_before,) = cursor.fetchone()
        cursor.execute(f'SELECT count(DISTINCT purchase_uuid) FROM "{THROUGH_TABLE}"')
        (linked_after,) = cursor.fetchone()
        cursor.execute(f'SELECT count(*) FROM "{THROUGH_TABLE}"')
        (through_rows_after,) = cursor.fetchone()
        if unmatched or through_rows_before != through_rows_after:
            raise RuntimeError(
                "Purchase through backfill did not preserve every row: "
                f"{through_rows_before=} {through_rows_after=} {unmatched=}"
            )
        if linked_before != linked_after:
            raise RuntimeError(
                "Purchase through backfill changed the linked Purchase count: "
                f"{linked_before} != {linked_after}"
            )

        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cursor.execute(f'ALTER TABLE "{THROUGH_TABLE}" DROP COLUMN purchase_id')
        cursor.execute(
            f'ALTER TABLE "{THROUGH_TABLE}" RENAME COLUMN purchase_uuid TO purchase_id'
        )
        cursor.execute(
            f'ALTER TABLE "{THROUGH_TABLE}" ALTER COLUMN purchase_id SET NOT NULL'
        )

        cursor.execute(f'SELECT count(*) FROM "{PURCHASE_TABLE}"')
        (purchase_rows_before,) = cursor.fetchone()
        cursor.execute(f'ALTER TABLE "{PURCHASE_TABLE}" DROP COLUMN id')
        cursor.execute(f'ALTER TABLE "{PURCHASE_TABLE}" RENAME COLUMN uuid TO id')
        cursor.execute(f'ALTER TABLE "{PURCHASE_TABLE}" ADD PRIMARY KEY (id)')
        _drop_redundant_unique_constraint(cursor)
        cursor.execute(f'SELECT count(*) FROM "{PURCHASE_TABLE}"')
        (purchase_rows_after,) = cursor.fetchone()
        if purchase_rows_before != purchase_rows_after:
            raise RuntimeError(
                "Purchase row count changed during identity promotion: "
                f"{purchase_rows_before} != {purchase_rows_after}"
            )

    _create_through_constraints(apps, schema_editor)
    print(
        "PUR identity promoted "
        f"purchase_rows={purchase_rows_after} "
        f"through_rows={through_rows_after} "
        f"through_purchases={linked_after} unmatched=0"
    )


def lock_purchase_tables(cursor):
    cursor.execute(
        f'LOCK TABLE "{PURCHASE_TABLE}", "{THROUGH_TABLE}" IN ACCESS EXCLUSIVE MODE'
    )


def restore_empty_purchase(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        lock_purchase_tables(cursor)
        cursor.execute(
            f"SELECT (SELECT count(*) FROM {PURCHASE_TABLE}), "
            f"(SELECT count(*) FROM {THROUGH_TABLE})"
        )
        purchases, through_rows = cursor.fetchone()
        if purchases or through_rows:
            raise RuntimeError(
                "Cannot reverse the Purchase identity promotion: the original "
                f"integer identities are gone and {purchases} purchase(s) and "
                f"{through_rows} purchase/game link(s) would need invented "
                "replacements. Restore from a backup taken before this migration "
                "instead."
            )

        cursor.execute(f'ALTER TABLE "{THROUGH_TABLE}" DROP COLUMN purchase_id')
        cursor.execute(f'ALTER TABLE "{PURCHASE_TABLE}" RENAME COLUMN id TO uuid')
        cursor.execute(
            f'ALTER TABLE "{PURCHASE_TABLE}" DROP CONSTRAINT "{PURCHASE_TABLE}_pkey"'
        )
        cursor.execute(f'ALTER TABLE "{PURCHASE_TABLE}" ADD UNIQUE (uuid)')
        cursor.execute(
            f'ALTER TABLE "{PURCHASE_TABLE}" ADD COLUMN id bigint '
            "GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY"
        )
        cursor.execute(
            f'ALTER TABLE "{THROUGH_TABLE}" ADD COLUMN purchase_id bigint NOT NULL'
        )

    _create_through_constraints(apps, schema_editor)


class Migration(migrations.Migration):
    dependencies = [
        ("games", "0014_session_playhistory_uuid_primary_key"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=promote_state(),
            database_operations=[],
        ),
        migrations.RunPython(promote_purchase_identity, restore_empty_purchase),
    ]
