"""State the two word sets, in Django's state."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("games", "0041_external_reference_marks"),
    ]

    operations = [
        migrations.AlterField(
            model_name="externalreference",
            name="entity_kind",
            field=models.CharField(
                choices=[
                    ("game", "Game"),
                    ("edition", "Edition"),
                    ("release", "Release"),
                    ("platform", "Platform"),
                ],
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="externalreference",
            name="provider",
            field=models.CharField(choices=[("wikidata", "Wikidata")], max_length=50),
        ),
    ]
