import django.db.models.deletion
from django.db import migrations, models

from timetracker.uuidv7 import UUIDv7Field

PROMOTED_TABLES = (
    ("device", "games_device"),
    ("filterpreset", "games_filterpreset"),
)
DEVICE_TABLE = "games_device"
DEVICE_RELATIONS = (
    ("session", "device"),
    ("userlibrarypreferences", "default_device"),
)
FK_SUFFIX = "_fk_%(to_table)s_%(to_column)s"


def promote_state(model_name):
    return [
        migrations.RemoveField(model_name=model_name, name="id"),
        migrations.RemoveField(model_name=model_name, name="uuid"),
        migrations.AddField(
            model_name=model_name,
            name="id",
            field=UUIDv7Field(
                primary_key=True,
                editable=False,
                serialize=False,
            ),
        ),
    ]


def relation_state(model_name, field_name, **options):
    return migrations.AlterField(
        model_name=model_name,
        name=field_name,
        field=models.ForeignKey(to="games.device", **options),
    )


def _device_fields(apps):
    return [
        (
            apps.get_model("games", model_name),
            apps.get_model("games", model_name)._meta.get_field(field_name),
        )
        for model_name, field_name in DEVICE_RELATIONS
    ]


def _drop_referencing_constraints(cursor, table_name):
    cursor.execute(
        """
        SELECT conrelid::regclass::text, conname
        FROM pg_constraint
        WHERE confrelid = %s::regclass AND contype = 'f'
        """,
        [table_name],
    )
    for child_table, constraint_name in cursor.fetchall():
        cursor.execute(
            f'ALTER TABLE "{child_table}" DROP CONSTRAINT "{constraint_name}"'
        )


def _drop_redundant_unique_constraint(cursor, table_name):
    cursor.execute(
        """
        SELECT conname FROM pg_constraint
        WHERE conrelid = %s::regclass AND contype = 'u'
          AND pg_get_constraintdef(oid) = 'UNIQUE (id)'
        """,
        [table_name],
    )
    for (constraint_name,) in cursor.fetchall():
        cursor.execute(
            f'ALTER TABLE "{table_name}" DROP CONSTRAINT "{constraint_name}"'
        )


def _create_device_constraints(apps, schema_editor):
    for model, field in _device_fields(apps):
        schema_editor.execute(schema_editor._create_fk_sql(model, field, FK_SUFFIX))


def promote_library_config_identities(apps, schema_editor):
    row_counts = {}
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        for _model_name, table_name in PROMOTED_TABLES:
            cursor.execute(f'SELECT count(*) FROM "{table_name}"')
            (row_counts[table_name],) = cursor.fetchone()

        _drop_referencing_constraints(cursor, DEVICE_TABLE)
        for _model_name, table_name in PROMOTED_TABLES:
            cursor.execute(f'ALTER TABLE "{table_name}" DROP COLUMN id')
            cursor.execute(f'ALTER TABLE "{table_name}" RENAME COLUMN uuid TO id')
            cursor.execute(f'ALTER TABLE "{table_name}" ADD PRIMARY KEY (id)')
            _drop_redundant_unique_constraint(cursor, table_name)

            cursor.execute(f'SELECT count(*) FROM "{table_name}"')
            (rows_after,) = cursor.fetchone()
            if rows_after != row_counts[table_name]:
                raise RuntimeError(
                    f"{table_name} row count changed during identity promotion: "
                    f"{row_counts[table_name]} != {rows_after}"
                )

    _create_device_constraints(apps, schema_editor)
    print(
        "LIB identity promoted "
        f"device_rows={row_counts['games_device']} "
        f"filterpreset_rows={row_counts['games_filterpreset']}"
    )


def lock_promoted_tables(cursor):
    tables = ", ".join(f'"{table_name}"' for _name, table_name in PROMOTED_TABLES)
    cursor.execute(f"LOCK TABLE {tables} IN ACCESS EXCLUSIVE MODE")


def _restore_device_constraints(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        for model, field in _device_fields(apps):
            table = model._meta.db_table
            column = field.column
            name = schema_editor._create_index_name(
                table,
                [column],
                suffix="_fk_games_device_uuid",
            )
            cursor.execute(
                f'ALTER TABLE "{table}" ADD CONSTRAINT "{name}" '
                f'FOREIGN KEY ("{column}") REFERENCES "{DEVICE_TABLE}" ("uuid") '
                "DEFERRABLE INITIALLY DEFERRED"
            )


def restore_empty_library_config(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        lock_promoted_tables(cursor)
        cursor.execute(
            "SELECT (SELECT count(*) FROM games_device), "
            "(SELECT count(*) FROM games_filterpreset)"
        )
        devices, presets = cursor.fetchone()
        if devices or presets:
            raise RuntimeError(
                "Cannot reverse the library configuration identity promotion: "
                "the original integer identities are gone and "
                f"{devices} device(s) and {presets} filter preset(s) would need "
                "invented replacements. Restore a pre-migration backup instead."
            )

        _drop_referencing_constraints(cursor, DEVICE_TABLE)
        for _model_name, table_name in PROMOTED_TABLES:
            cursor.execute(f'ALTER TABLE "{table_name}" RENAME COLUMN id TO uuid')
            cursor.execute(
                f'ALTER TABLE "{table_name}" DROP CONSTRAINT "{table_name}_pkey"'
            )
            cursor.execute(f'ALTER TABLE "{table_name}" ADD UNIQUE (uuid)')
            cursor.execute(
                f'ALTER TABLE "{table_name}" ADD COLUMN id bigint '
                "GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY"
            )

    _restore_device_constraints(apps, schema_editor)


class Migration(migrations.Migration):
    dependencies = [
        ("games", "0015_purchase_uuid_primary_key"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                *promote_state("device"),
                *promote_state("filterpreset"),
                relation_state(
                    "session",
                    "device",
                    blank=True,
                    default=None,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                ),
                relation_state(
                    "userlibrarypreferences",
                    "default_device",
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="+",
                ),
            ],
            database_operations=[],
        ),
        migrations.RunPython(
            promote_library_config_identities,
            restore_empty_library_config,
        ),
    ]
