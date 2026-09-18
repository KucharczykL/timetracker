import django.db.models.deletion
from django.db import migrations, models

#: The latest restate event per record, so a replay agrees.
STATE_RESTATED_AT = """
UPDATE games_historicalplaytime AS record
SET restated_at = latest.recorded_at
FROM (
    SELECT aggregate_id, library_id, max(recorded_at) AS recorded_at
    FROM games_libraryevent
    WHERE event_type = 'library.historicalplaytime.restated'
    GROUP BY aggregate_id, library_id
) AS latest
WHERE record.id = latest.aggregate_id
  AND record.library_id = latest.library_id
"""


def state_restated_at(apps, schema_editor):
    schema_editor.execute(STATE_RESTATED_AT)


class Migration(migrations.Migration):
    dependencies = [
        ("games", "0010_alter_filterpreset_mode"),
    ]

    operations = [
        migrations.AddField(
            model_name="historicalplaytime",
            name="restated_at",
            field=models.DateTimeField(default=None, editable=False, null=True),
        ),
        migrations.AddField(
            model_name="historicalplaytime",
            name="reclassified_from",
            field=models.ForeignKey(
                default=None,
                null=True,
                on_delete=django.db.models.deletion.RESTRICT,
                related_name="reclassified_records",
                to="games.playersession",
            ),
        ),
        migrations.RunPython(state_restated_at, migrations.RunPython.noop),
    ]
