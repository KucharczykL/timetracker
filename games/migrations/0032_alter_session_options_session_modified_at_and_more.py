# Generated by Django 4.1.5 on 2023-11-15 18:02

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("games", "0031_device_created_at_edition_created_at_game_created_at_and_more"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="session",
            options={"get_latest_by": "timestamp_start"},
        ),
        migrations.AddField(
            model_name="session",
            name="modified_at",
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.AlterField(
            model_name="device",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True),
        ),
        migrations.AlterField(
            model_name="edition",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True),
        ),
        migrations.AlterField(
            model_name="game",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True),
        ),
        migrations.AlterField(
            model_name="platform",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True),
        ),
        migrations.AlterField(
            model_name="purchase",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True),
        ),
        migrations.AlterField(
            model_name="session",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True),
        ),
    ]
