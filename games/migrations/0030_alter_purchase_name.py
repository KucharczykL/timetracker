# Generated by Django 4.1.5 on 2023-11-15 12:04

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("games", "0029_alter_purchase_related_purchase"),
    ]

    operations = [
        migrations.AlterField(
            model_name="purchase",
            name="name",
            field=models.CharField(blank=True, default="", max_length=255, null=True),
        ),
    ]
