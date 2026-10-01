from django.db import migrations

#: Renaming a table keeps its index names.
_RENAME_INDEXES = """
DO $$
DECLARE
    index_name text;
BEGIN
    FOR index_name IN
        SELECT index_class.relname
        FROM pg_index
        JOIN pg_class index_class ON index_class.oid = pg_index.indexrelid
        JOIN pg_class table_class ON table_class.oid = pg_index.indrelid
        WHERE table_class.relname IN ('{table}', '{table}_games')
          AND index_class.relname LIKE '{old}\\_%'
    LOOP
        EXECUTE format(
            'ALTER INDEX %I RENAME TO %I',
            index_name,
            '{new}' || substr(index_name, length('{old}') + 1)
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
            _RENAME_INDEXES.format(
                table="games_legacypurchase",
                old="games_purchase",
                new="games_legacypurchase",
            ),
            reverse_sql=_RENAME_INDEXES.format(
                table="games_legacypurchase",
                old="games_legacypurchase",
                new="games_purchase",
            ),
        ),
    ]
