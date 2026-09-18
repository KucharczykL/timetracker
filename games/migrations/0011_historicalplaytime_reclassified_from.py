import django.db.models.deletion
from django.db import migrations, models

#: The last restate event, in stream order.
#: `max(recorded_at)` agrees only while `recorded_at` is
#: monotonic with `sequence`; a replay reads the sequence, and
#: `verify-replay-parity` is the only thing that would notice.
STATE_RESTATED_AT = """
UPDATE games_historicalplaytime AS record
SET restated_at = latest.recorded_at
FROM (
    SELECT DISTINCT ON (library_id, aggregate_id)
        library_id, aggregate_id, recorded_at
    FROM games_libraryevent
    WHERE event_type = 'library.historicalplaytime.restated'
    ORDER BY library_id, aggregate_id, sequence DESC
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
        migrations.AddConstraint(
            model_name="historicalplaytime",
            constraint=models.UniqueConstraint(
                condition=models.Q(
                    ("reclassified_from__isnull", False), ("removed_at__isnull", True)
                ),
                fields=("reclassified_from",),
                name="historicalplaytime_one_live_per_session",
            ),
        ),
        migrations.RunPython(state_restated_at, migrations.RunPython.noop),
    ]
