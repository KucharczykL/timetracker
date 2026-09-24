import django.db.models.deletion
import django.db.models.fields
from django.db import migrations, models

import timetracker.uuidv7


class Migration(migrations.Migration):
    dependencies = [
        ("games", "0013_list_column_choice"),
    ]

    operations = [
        migrations.AlterField(
            model_name="device",
            name="created_at",
            field=models.DateTimeField(editable=False),
        ),
        #: Django cannot compile an altered db_default of NOT_PROVIDED,
        #: so the state and the column move apart.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="device",
                    name="id",
                    field=timetracker.uuidv7.UUIDv7Field(
                        db_default=django.db.models.fields.NOT_PROVIDED,
                        default=django.db.models.fields.NOT_PROVIDED,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    "ALTER TABLE games_device ALTER COLUMN id DROP DEFAULT",
                    reverse_sql=(
                        "ALTER TABLE games_device ALTER COLUMN id SET DEFAULT uuidv7()"
                    ),
                ),
            ],
        ),
        migrations.AlterField(
            model_name="device",
            name="library",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="+",
                to="games.userlibrary",
            ),
        ),
        migrations.AddConstraint(
            model_name="device",
            constraint=models.UniqueConstraint(
                fields=("id", "library"), name="unique_games_device_library_identity"
            ),
        ),
    ]
