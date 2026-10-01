from django.db import migrations

#: A table rename keeps index and constraint names.
_RENAME_NAMES = """
DO $$
DECLARE
    found record;
    new_name text;
BEGIN
    FOR found IN
        SELECT index_class.relname AS name
        FROM pg_index
        JOIN pg_class index_class ON index_class.oid = pg_index.indexrelid
        JOIN pg_class table_class ON table_class.oid = pg_index.indrelid
        WHERE table_class.relname IN ('{table}', '{table}_games')
          AND index_class.relname LIKE '{old}\\_%'
    LOOP
        new_name := '{new}' || substr(found.name, length('{old}') + 1);
        IF length(new_name) > 63 THEN
            RAISE EXCEPTION 'Index % would be truncated as %.', found.name, new_name;
        END IF;
        EXECUTE format('ALTER INDEX %I RENAME TO %I', found.name, new_name);
    END LOOP;
    FOR found IN
        SELECT pg_constraint.conname AS name, table_class.relname AS owner
        FROM pg_constraint
        JOIN pg_class table_class ON table_class.oid = pg_constraint.conrelid
        WHERE table_class.relname IN ('{table}', '{table}_games')
          AND pg_constraint.conname LIKE '{old}\\_%'
    LOOP
        -- Cut to 63, as PostgreSQL would; refuse a clash.
        new_name := left('{new}' || substr(found.name, length('{old}') + 1), 63);
        IF EXISTS (
            SELECT 1 FROM pg_constraint
            JOIN pg_class owner_class ON owner_class.oid = pg_constraint.conrelid
            WHERE owner_class.relname = found.owner
              AND pg_constraint.conname = new_name
        ) THEN
            RAISE EXCEPTION 'Constraint % would become %, which exists.',
                found.name, new_name;
        END IF;
        EXECUTE format(
            'ALTER TABLE %I RENAME CONSTRAINT %I TO %I',
            found.owner,
            found.name,
            new_name
        );
    END LOOP;
END
$$;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("games", "0025_playergame_excluded_from_dropped"),
    ]

    operations = [
        migrations.RenameModel("Purchase", "LegacyPurchase"),
        migrations.AlterModelOptions(
            name="legacypurchase",
            options={"verbose_name": "purchase", "verbose_name_plural": "purchases"},
        ),
        migrations.RunSQL(
            _RENAME_NAMES.format(
                table="games_legacypurchase",
                old="games_purchase",
                new="games_legacypurchase",
            ),
            reverse_sql=_RENAME_NAMES.format(
                table="games_legacypurchase",
                old="games_legacypurchase",
                new="games_purchase",
            ),
        ),
    ]
