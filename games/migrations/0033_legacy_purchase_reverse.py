"""Legacy purchases lose their reverse accessors.

State only: every remaining read walks forward.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("games", "0032_purchase_presets"),
    ]

    operations = [
        migrations.AlterField(
            model_name="legacypurchase",
            name="library",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="+",
                to="games.userlibrary",
            ),
        ),
        migrations.AlterField(
            model_name="legacypurchase",
            name="games",
            field=models.ManyToManyField(related_name="+", to="games.game"),
        ),
        migrations.AlterField(
            model_name="legacypurchase",
            name="platform",
            field=models.ForeignKey(
                blank=True,
                default=None,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="games.platform",
            ),
        ),
        migrations.AlterField(
            model_name="legacypurchase",
            name="related_game",
            field=models.ForeignKey(
                blank=True,
                default=None,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="games.game",
                verbose_name="Base game",
            ),
        ),
    ]
