# Generated by Django 5.1.5 on 2025-01-29 17:34

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('games', '0048_game_platform'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='game',
            unique_together={('name', 'platform', 'year_released')},
        ),
    ]
