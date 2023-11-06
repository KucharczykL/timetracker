from django.db import migrations


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
    dependencies = [
        ("games", "0020_game_year"),
    ]

    operations = [
        migrations.RunPython(update_game_year),
    ]
