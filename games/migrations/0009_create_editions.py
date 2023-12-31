# Generated by Django 4.1.5 on 2023-02-18 18:51

from django.db import migrations


def create_edition_of_game(apps, schema_editor):
    Game = apps.get_model("games", "Game")
    Edition = apps.get_model("games", "Edition")
    Platform = apps.get_model("games", "Platform")
    first_platform = Platform.objects.first()
    all_games = Game.objects.all()
    all_editions = Edition.objects.all()
    for game in all_games:
        existing_edition = None
        try:
            existing_edition = all_editions.objects.get(game=game.id)
        except:
            pass
        if existing_edition == None:
            edition = Edition()
            edition.id = game.id
            edition.game = game
            edition.name = game.name
            edition.platform = first_platform
            edition.save()


class Migration(migrations.Migration):

    dependencies = [
        ("games", "0008_edition"),
    ]

    operations = [migrations.RunPython(create_edition_of_game)]
