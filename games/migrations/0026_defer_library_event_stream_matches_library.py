from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("games", "0025_playergame_excluded_from_dropped"),
    ]

    operations = [
        #: Checked at commit, as Django's own keys.
        migrations.RunSQL(
            sql="ALTER TABLE games_libraryevent\n"
            "    ALTER CONSTRAINT library_event_stream_matches_library\n"
            "    DEFERRABLE INITIALLY DEFERRED;",
            reverse_sql="ALTER TABLE games_libraryevent\n"
            "    ALTER CONSTRAINT library_event_stream_matches_library\n"
            "    NOT DEFERRABLE;",
        ),
    ]
