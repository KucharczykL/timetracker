# Generated by Django 4.1.5 on 2023-11-06 18:14

import django.db.models.deletion
from django.db import migrations, models


def rename_duplicates(apps, schema_editor):
    Edition = apps.get_model("games", "Edition")

    duplicates = (
        Edition.objects.values("name", "platform")
        .annotate(name_count=models.Count("id"))
        .filter(name_count__gt=1)
    )

    for duplicate in duplicates:
        counter = 1
        duplicate_editions = Edition.objects.filter(
            name=duplicate["name"], platform_id=duplicate["platform"]
        ).order_by("id")

        for edition in duplicate_editions[1:]:  # Skip the first one
            edition.name = f"{edition.name} {counter}"
            edition.save()
            counter += 1


def update_game_year(apps, schema_editor):
    Game = apps.get_model("games", "Game")
    Edition = apps.get_model("games", "Edition")

    for game in Game.objects.filter(year__isnull=True):
        # Try to get the first related edition with a non-null year_released
        edition = Edition.objects.filter(game=game, year_released__isnull=False).first()
        if edition:
            # If an edition is found, update the game's year
            game.year = edition.year_released
            game.save()


class Migration(migrations.Migration):
    replaces = [
        ("games", "0016_alter_edition_platform_alter_edition_year_released_and_more"),
        ("games", "0017_alter_device_type_alter_purchase_platform"),
        ("games", "0018_auto_20231106_1825"),
        ("games", "0019_alter_edition_unique_together"),
        ("games", "0020_game_year"),
        ("games", "0021_auto_20231106_1909"),
        ("games", "0022_rename_year_game_year_released"),
    ]

    dependencies = [
        ("games", "0015_edition_wikidata_edition_year_released"),
    ]

    operations = [
        migrations.AlterField(
            model_name="edition",
            name="platform",
            field=models.ForeignKey(
                blank=True,
                default=None,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                to="games.platform",
            ),
        ),
        migrations.AlterField(
            model_name="edition",
            name="year_released",
            field=models.IntegerField(blank=True, default=None, null=True),
        ),
        migrations.AlterField(
            model_name="game",
            name="wikidata",
            field=models.CharField(blank=True, default=None, max_length=50, null=True),
        ),
        migrations.AlterField(
            model_name="platform",
            name="group",
            field=models.CharField(blank=True, default=None, max_length=255, null=True),
        ),
        migrations.AlterField(
            model_name="session",
            name="device",
            field=models.ForeignKey(
                blank=True,
                default=None,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                to="games.device",
            ),
        ),
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
        migrations.RunPython(
            code=rename_duplicates,
        ),
        migrations.AlterUniqueTogether(
            name="edition",
            unique_together={("name", "platform")},
        ),
        migrations.AddField(
            model_name="game",
            name="year",
            field=models.IntegerField(blank=True, default=None, null=True),
        ),
        migrations.RunPython(
            code=update_game_year,
        ),
        migrations.RenameField(
            model_name="game",
            old_name="year",
            new_name="year_released",
        ),
    ]
