"""The default device stores a key."""

from django.db import migrations, models

#: Every constraint and index on the column.
DROP_REFERENCE = """
DO $$
DECLARE found record;
BEGIN
    FOR found IN
        SELECT con.conname
        FROM pg_constraint con
        JOIN pg_attribute att
          ON att.attrelid = con.conrelid AND att.attnum = ANY (con.conkey)
        WHERE con.conrelid = 'games_userlibrarypreferences'::regclass
          AND con.contype = 'f'
          AND att.attname = 'default_device_id'
    LOOP
        EXECUTE format(
            'ALTER TABLE games_userlibrarypreferences DROP CONSTRAINT %I',
            found.conname
        );
    END LOOP;
    FOR found IN
        SELECT index_class.relname
        FROM pg_index idx
        JOIN pg_class index_class ON index_class.oid = idx.indexrelid
        JOIN pg_attribute att
          ON att.attrelid = idx.indrelid AND att.attnum = ANY (idx.indkey)
        WHERE idx.indrelid = 'games_userlibrarypreferences'::regclass
          AND NOT idx.indisprimary
          AND att.attname = 'default_device_id'
    LOOP
        EXECUTE format('DROP INDEX %I', found.relname);
    END LOOP;
END $$;
"""

RESTORE_REFERENCE = """
CREATE INDEX games_userlibrarypreferences_default_device_id
    ON games_userlibrarypreferences (default_device_id);
ALTER TABLE games_userlibrarypreferences
    ADD CONSTRAINT games_userlibrarypreferences_default_device_id_fk
    FOREIGN KEY (default_device_id) REFERENCES games_device (id)
    DEFERRABLE INITIALLY DEFERRED;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("games", "0015_device_conversion"),
    ]

    operations = [
        #: Same column; only the constraint goes.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(
                    model_name="userlibrarypreferences",
                    name="default_device",
                ),
                migrations.AddField(
                    model_name="userlibrarypreferences",
                    name="default_device_id",
                    field=models.UUIDField(blank=True, default=None, null=True),
                ),
            ],
            database_operations=[
                migrations.RunSQL(DROP_REFERENCE, reverse_sql=RESTORE_REFERENCE),
            ],
        ),
    ]
