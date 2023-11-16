# Generated by Django 4.1.5 on 2023-11-14 21:19

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("games", "0028_purchase_name"),
    ]

    operations = [
        migrations.AlterField(
            model_name="purchase",
            name="related_purchase",
            field=models.ForeignKey(
                blank=True,
                default=None,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="related_purchases",
                to="games.purchase",
            ),
        ),
    ]