# Generated by Django 4.1.5 on 2023-02-18 19:06

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("games", "0009_create_editions"),
    ]

    operations = [
        migrations.AlterField(
            model_name="purchase",
            name="game",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE, to="games.edition"
            ),
        ),
    ]