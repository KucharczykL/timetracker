# Generated by Django 4.1.4 on 2022-12-31 13:03

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tracker", "0002_game_platform_purchase_session_delete_trackermodel"),
    ]

    operations = [
        migrations.AlterField(
            model_name="purchase",
            name="date_purchased",
            field=models.DateField(),
        ),
        migrations.AlterField(
            model_name="purchase",
            name="date_refunded",
            field=models.DateField(),
        ),
    ]
