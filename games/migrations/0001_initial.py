# Generated by Django 5.1.5 on 2025-01-29 21:26

import datetime
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='Device',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255)),
                ('type', models.CharField(choices=[('PC', 'PC'), ('Console', 'Console'), ('Handheld', 'Handheld'), ('Mobile', 'Mobile'), ('Single-board computer', 'Single-board computer'), ('Unknown', 'Unknown')], default='Unknown', max_length=255)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.CreateModel(
            name='Platform',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255)),
                ('group', models.CharField(blank=True, default=None, max_length=255, null=True)),
                ('icon', models.SlugField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.CreateModel(
            name='ExchangeRate',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('currency_from', models.CharField(max_length=255)),
                ('currency_to', models.CharField(max_length=255)),
                ('year', models.PositiveIntegerField()),
                ('rate', models.FloatField()),
            ],
            options={
                'unique_together': {('currency_from', 'currency_to', 'year')},
            },
        ),
        migrations.CreateModel(
            name='Game',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255)),
                ('sort_name', models.CharField(blank=True, default=None, max_length=255, null=True)),
                ('year_released', models.IntegerField(blank=True, default=None, null=True)),
                ('wikidata', models.CharField(blank=True, default=None, max_length=50, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('platform', models.ForeignKey(blank=True, default=None, null=True, on_delete=django.db.models.deletion.SET_DEFAULT, to='games.platform')),
            ],
            options={
                'unique_together': {('name', 'platform', 'year_released')},
            },
        ),
        migrations.CreateModel(
            name='Purchase',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date_purchased', models.DateField()),
                ('date_refunded', models.DateField(blank=True, null=True)),
                ('date_finished', models.DateField(blank=True, null=True)),
                ('date_dropped', models.DateField(blank=True, null=True)),
                ('infinite', models.BooleanField(default=False)),
                ('price', models.FloatField(default=0)),
                ('price_currency', models.CharField(default='USD', max_length=3)),
                ('converted_price', models.FloatField(null=True)),
                ('converted_currency', models.CharField(max_length=3, null=True)),
                ('ownership_type', models.CharField(choices=[('ph', 'Physical'), ('di', 'Digital'), ('du', 'Digital Upgrade'), ('re', 'Rented'), ('bo', 'Borrowed'), ('tr', 'Trial'), ('de', 'Demo'), ('pi', 'Pirated')], default='di', max_length=2)),
                ('type', models.CharField(choices=[('game', 'Game'), ('dlc', 'DLC'), ('season_pass', 'Season Pass'), ('battle_pass', 'Battle Pass')], default='game', max_length=255)),
                ('name', models.CharField(blank=True, default='', max_length=255, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('games', models.ManyToManyField(blank=True, related_name='purchases', to='games.game')),
                ('platform', models.ForeignKey(blank=True, default=None, null=True, on_delete=django.db.models.deletion.CASCADE, to='games.platform')),
                ('related_purchase', models.ForeignKey(blank=True, default=None, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='related_purchases', to='games.purchase')),
            ],
        ),
        migrations.CreateModel(
            name='Session',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('timestamp_start', models.DateTimeField()),
                ('timestamp_end', models.DateTimeField(blank=True, null=True)),
                ('duration_manual', models.DurationField(blank=True, default=datetime.timedelta(0), null=True)),
                ('duration_calculated', models.DurationField(blank=True, null=True)),
                ('note', models.TextField(blank=True, null=True)),
                ('emulated', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('modified_at', models.DateTimeField(auto_now=True)),
                ('device', models.ForeignKey(blank=True, default=None, null=True, on_delete=django.db.models.deletion.SET_DEFAULT, to='games.device')),
                ('game', models.ForeignKey(blank=True, default=None, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='sessions', to='games.game')),
            ],
            options={
                'get_latest_by': 'timestamp_start',
            },
        ),
    ]
