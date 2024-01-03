# Generated by Django 4.2.7 on 2024-01-03 21:27

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("games", "0033_alter_edition_unique_together"),
    ]

    operations = [
        migrations.AddField(
            model_name="purchase",
            name="date_dropped",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="purchase",
            name="infinite",
            field=models.BooleanField(default=False),
        ),
    ]
