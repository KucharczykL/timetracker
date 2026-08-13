from django.db import migrations

CREATE_UUID_V7_DOMAIN = """
CREATE DOMAIN uuid_v7 AS uuid
CHECK (
    VALUE IS NULL
    OR uuid_extract_version(VALUE) IS NOT DISTINCT FROM 7
)
""".strip()

DROP_UUID_V7_DOMAIN = "DROP DOMAIN uuid_v7"


class Migration(migrations.Migration):
    dependencies = [
        ("games", "0001_squashed_0036_alter_playevent_days_to_finish"),
    ]

    operations = [
        migrations.RunSQL(
            sql=CREATE_UUID_V7_DOMAIN,
            reverse_sql=DROP_UUID_V7_DOMAIN,
        ),
    ]
