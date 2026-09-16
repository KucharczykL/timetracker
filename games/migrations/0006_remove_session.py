from django.db import migrations

UNCONVERTED_ROWS = """
SELECT count(*) FROM games_session AS row
WHERE NOT EXISTS (
    SELECT 1 FROM games_libraryevent AS event
    WHERE event.aggregate_id = row.id
      AND event.event_type = 'library.playersession.created'
)
"""


def refuse_unconverted_rows(apps, schema_editor):
    """Refuse to drop a row no event records.

    Raw SQL, never the application's models: every fresh database runs
    this callable, whatever `elidable` says to the optimizer.
    """
    del apps
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(UNCONVERTED_ROWS)
        (unconverted,) = cursor.fetchone()
    if unconverted:
        raise RuntimeError(
            f"{unconverted} legacy session row(s) have no event; upgrade "
            "through a release that applied 0004_playersession_conversion "
            "before this one."
        )


class Migration(migrations.Migration):
    dependencies = [
        ("games", "0005_library_calendar"),
    ]

    operations = [
        migrations.RunPython(
            refuse_unconverted_rows, migrations.RunPython.noop, elidable=True
        ),
        migrations.RemoveIndex(
            model_name="session",
            name="session_start_id_idx",
        ),
        migrations.DeleteModel(
            name="Session",
        ),
    ]
