# Generated by Django 5.1.5 on 2025-01-30 11:12

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('games', '0002_purchase_price_per_game'),
    ]

    operations = [
        migrations.AddField(
            model_name='purchase',
            name='updated_at',
            field=models.DateTimeField(auto_now=True),
        ),
    ]
