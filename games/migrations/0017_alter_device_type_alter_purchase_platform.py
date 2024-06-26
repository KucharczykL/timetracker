# Generated by Django 4.1.5 on 2023-11-06 16:53

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("games", "0016_alter_edition_platform_alter_edition_year_released_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="device",
            name="type",
            field=models.CharField(
                choices=[
                    ("pc", "PC"),
                    ("co", "Console"),
                    ("ha", "Handheld"),
                    ("mo", "Mobile"),
                    ("sbc", "Single-board computer"),
                    ("un", "Unknown"),
                ],
                default="un",
                max_length=3,
            ),
        ),
        migrations.AlterField(
            model_name="purchase",
            name="platform",
            field=models.ForeignKey(
                blank=True,
                default=None,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                to="games.platform",
            ),
        ),
    ]
