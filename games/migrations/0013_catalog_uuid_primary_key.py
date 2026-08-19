import django.db.models.deletion
from django.db import migrations, models

from timetracker.uuidv7 import UUIDv7Field

# The foreign keys that resolve through Game.uuid and Platform.uuid while those
# are secondary columns, and through the primary key once they are promoted.
# Named here so the schema work below can take each constraint down and put it
# back under the name Django itself would generate.
GAME_RELATIONS = [
    ("purchase", "related_game"),
    ("session", "game"),
    ("playevent", "game"),
    ("gamestatuschange", "game"),
]
PLATFORM_RELATIONS = [
    ("game", "platform"),
    ("purchase", "platform"),
]
CATALOG_RELATIONS = GAME_RELATIONS + PLATFORM_RELATIONS

THROUGH_TABLE = "games_purchase_games"
FK_SUFFIX = "_fk_%(to_table)s_%(to_column)s"


def promote_state(model_name):
    """State-only promotion of one model's uuid to its primary key.

    Drop-and-add rather than `RenameField`, which is not a safe way to retire
    the name of a column other models reach through `to_field`:
    `ProjectState.rename_field` rewrites every referring relation's
    `remote_field.field_name` *in place*, and those relation objects are shared
    with the states of the migrations that declared them. One forward pass is
    enough to leave every historical state believing those foreign keys always
    pointed at the primary key, which then mis-types the column on any later
    replay - the failure mode a migration-harness test hits when it reverses
    past this migration and re-applies it in the same process.
    """
    return [
        migrations.RemoveField(model_name=model_name, name="id"),
        migrations.RemoveField(model_name=model_name, name="uuid"),
        migrations.AddField(
            model_name=model_name,
            name="id",
            field=UUIDv7Field(primary_key=True, editable=False, serialize=False),
        ),
    ]


def relation_state(target, model_name, field_name, **options):
    return migrations.AlterField(
        model_name=model_name,
        name=field_name,
        field=models.ForeignKey(to=target, **options),
    )


def _catalog_fields(apps):
    """Each promoted relation as a (model, field) pair, from the current state."""
    return [
        (
            apps.get_model("games", model_name),
            apps.get_model("games", model_name)._meta.get_field(field_name),
        )
        for model_name, field_name in CATALOG_RELATIONS
    ]


def _drop_referencing_constraints(cursor, table_name):
    """Drop every foreign key pointing at a table, returning nothing.

    Introspected rather than named: the constraint names carry a hash of the
    table and column, and reading them back is more robust than restating
    them here.
    """
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


def _drop_redundant_unique_index(cursor, table_name):
    """Remove the old `unique=True` index left over beside the new primary key.

    `primary_key=True` subsumes `unique=True`, so this index is pure overhead
    once the column is the key. It cannot come off before the referencing
    foreign keys do - they depend on this specific index, and `CASCADE` would
    take them with it.
    """
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


def promote_catalog_identities(apps, schema_editor):
    """Make the catalog's uuid its primary key, and drop the legacy integer.

    Every step's position here is forced, and each was established by running
    the sequence against a real database:

    1. The through table converts first. `DROP COLUMN games_game.id` fails
       while `games_purchase_games.game_id` still references it.
    2. The referencing foreign keys come off before the promotion, because the
       redundant unique index cannot be dropped while they depend on it.
    3. The through table's `DROP COLUMN` silently cascades away both its
       `(purchase_id, game_id)` unique index and its `game_id` index, which
       Django's migration state never stops listing - so nothing else would
       report their absence. They are rebuilt at the end.
    """
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        cursor.execute(f'ALTER TABLE "{THROUGH_TABLE}" ADD COLUMN game_uuid uuid_v7')
        cursor.execute(
            f"""
            UPDATE "{THROUGH_TABLE}" AS through
            SET game_uuid = target.uuid
            FROM games_game AS target
            WHERE target.id = through.game_id
            """
        )
        cursor.execute(f'SELECT count(*) FROM "{THROUGH_TABLE}"')
        (row_count,) = cursor.fetchone()
        cursor.execute(
            f'SELECT count(*) FROM "{THROUGH_TABLE}" WHERE game_uuid IS NULL'
        )
        (unmatched,) = cursor.fetchone()
        if unmatched:
            raise RuntimeError(
                f"through backfill left {unmatched} of {row_count} rows unmatched"
            )
        cursor.execute(f'SELECT count(DISTINCT game_id) FROM "{THROUGH_TABLE}"')
        (games_before,) = cursor.fetchone()
        cursor.execute(f'SELECT count(DISTINCT game_uuid) FROM "{THROUGH_TABLE}"')
        (games_after,) = cursor.fetchone()
        if games_before != games_after:
            raise RuntimeError(
                "through backfill changed the linked game count: "
                f"{games_before} != {games_after}"
            )
        # Every foreign key here is DEFERRABLE INITIALLY DEFERRED, so the UPDATE
        # above leaves a pending trigger event and the ALTER TABLEs below fail
        # with "cannot ALTER TABLE because it has pending trigger events".
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cursor.execute(f'ALTER TABLE "{THROUGH_TABLE}" DROP COLUMN game_id')
        cursor.execute(
            f'ALTER TABLE "{THROUGH_TABLE}" RENAME COLUMN game_uuid TO game_id'
        )
        cursor.execute(
            f'ALTER TABLE "{THROUGH_TABLE}" ALTER COLUMN game_id SET NOT NULL'
        )

        for table_name in ("games_game", "games_platform"):
            _drop_referencing_constraints(cursor, table_name)
            cursor.execute(f'ALTER TABLE "{table_name}" DROP COLUMN id')
            cursor.execute(f'ALTER TABLE "{table_name}" RENAME COLUMN uuid TO id')
            cursor.execute(f'ALTER TABLE "{table_name}" ADD PRIMARY KEY (id)')
            _drop_redundant_unique_index(cursor, table_name)

    _create_catalog_constraints(apps, schema_editor)

    print(
        f"CAT identity promoted through_rows={row_count} "
        f"through_games={games_after} unmatched=0"
    )


def _create_catalog_constraints(apps, schema_editor):
    """Rebuild every dropped constraint under Django's own generated names.

    The names matter beyond tidiness: ID-13 performs the mirror conversion on
    this table's `purchase_id`, and Django's schema editor looks constraints up
    by the names it would have generated.
    """
    for model, field in _catalog_fields(apps):
        schema_editor.execute(schema_editor._create_fk_sql(model, field, FK_SUFFIX))

    through = apps.get_model("games", "Purchase").games.through
    game_field = through._meta.get_field("game")
    schema_editor.execute(schema_editor._create_fk_sql(through, game_field, FK_SUFFIX))
    schema_editor.execute(schema_editor._create_index_sql(through, fields=[game_field]))
    schema_editor.alter_unique_together(through, [], [("purchase", "game")])


def restore_empty_catalog(apps, schema_editor):
    """Reverse the promotion, but only into an empty catalog.

    Dropping `games_game.id` destroyed the integer identities. Nothing remains
    to restore them from, and renumbering would mint values that merely
    resemble the originals, so a populated rollback fails loudly instead. An
    empty catalog has nothing to renumber, which is what lets the
    migration-harness tests reverse past this point.
    """
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT (SELECT count(*) FROM games_game), "
            "(SELECT count(*) FROM games_platform)"
        )
        games, platforms = cursor.fetchone()
        if games or platforms:
            raise RuntimeError(
                "Cannot reverse the catalog identity promotion: the original "
                f"integer identities are gone and {games} game(s) and "
                f"{platforms} platform(s) would need invented replacements. "
                "Restore from a backup taken before this migration instead."
            )

        for table_name in ("games_game", "games_platform"):
            _drop_referencing_constraints(cursor, table_name)
            cursor.execute(f'ALTER TABLE "{table_name}" RENAME COLUMN id TO uuid')
            cursor.execute(
                f'ALTER TABLE "{table_name}" DROP CONSTRAINT "{table_name}_pkey"'
            )
            cursor.execute(f'ALTER TABLE "{table_name}" ADD UNIQUE (uuid)')
            cursor.execute(
                f'ALTER TABLE "{table_name}" ADD COLUMN id bigint '
                "GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY"
            )

        cursor.execute(f'ALTER TABLE "{THROUGH_TABLE}" DROP COLUMN game_id')
        cursor.execute(f'ALTER TABLE "{THROUGH_TABLE}" ADD COLUMN game_id bigint')

    _restore_pre_promotion_constraints(apps, schema_editor)


def _restore_pre_promotion_constraints(apps, schema_editor):
    """Point every catalog foreign key back at the `uuid` column."""
    with schema_editor.connection.cursor() as cursor:
        for model_name, field_name in CATALOG_RELATIONS:
            model = apps.get_model("games", model_name)
            table = model._meta.db_table
            column = model._meta.get_field(field_name).column
            target = (
                "games_game" if (model_name, field_name) in GAME_RELATIONS else None
            )
            target = target or "games_platform"
            name = schema_editor._create_index_name(
                table, [column], suffix=f"_fk_{target}_uuid"
            )
            cursor.execute(
                f'ALTER TABLE "{table}" ADD CONSTRAINT "{name}" '
                f'FOREIGN KEY ("{column}") REFERENCES "{target}" ("uuid") '
                "DEFERRABLE INITIALLY DEFERRED"
            )
        name = schema_editor._create_index_name(
            THROUGH_TABLE, ["game_id"], suffix="_fk_games_game_id"
        )
        cursor.execute(
            f'ALTER TABLE "{THROUGH_TABLE}" ADD CONSTRAINT "{name}" '
            'FOREIGN KEY ("game_id") REFERENCES "games_game" ("id") '
            "DEFERRABLE INITIALLY DEFERRED"
        )
        index_name = schema_editor._create_index_name(
            THROUGH_TABLE, ["game_id"], suffix=""
        )
        cursor.execute(f'CREATE INDEX "{index_name}" ON "{THROUGH_TABLE}" ("game_id")')
        unique_name = schema_editor._create_index_name(
            THROUGH_TABLE, ["purchase_id", "game_id"], suffix="_uniq"
        )
        cursor.execute(
            f'ALTER TABLE "{THROUGH_TABLE}" ADD CONSTRAINT "{unique_name}" '
            'UNIQUE ("purchase_id", "game_id")'
        )


class Migration(migrations.Migration):
    dependencies = [
        ("games", "0012_purchase_related_game_uuid"),
    ]

    operations = [
        # State and database are separated deliberately. Expressed as ordinary
        # AlterField operations, the detach/reattach of a relation whose target
        # changes identity mid-migration resolves that target to the primary key
        # rather than to the declared `to_field` - reproducible whenever the
        # migration is reversed and re-applied in one process, which is what
        # every migration-harness test does. Owning the DDL keeps the schema
        # independent of how Django resolves a relation whose target is moving.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                *promote_state("game"),
                *promote_state("platform"),
                relation_state(
                    "games.game",
                    "purchase",
                    "related_game",
                    blank=True,
                    default=None,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="addon_purchases",
                    verbose_name="Base game",
                ),
                relation_state(
                    "games.game",
                    "session",
                    "game",
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="sessions",
                ),
                relation_state(
                    "games.game",
                    "playevent",
                    "game",
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="playevents",
                ),
                relation_state(
                    "games.game",
                    "gamestatuschange",
                    "game",
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="status_changes",
                ),
                relation_state(
                    "games.platform",
                    "game",
                    "platform",
                    blank=True,
                    default=None,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                ),
                relation_state(
                    "games.platform",
                    "purchase",
                    "platform",
                    blank=True,
                    default=None,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                ),
            ],
            database_operations=[],
        ),
        # Runs after the state operations above, so the models it reads already
        # describe the promoted schema and Django's own SQL builders generate
        # the constraint names for it.
        migrations.RunPython(promote_catalog_identities, restore_empty_catalog),
    ]
