# Generated by Django 4.1.5 on 2023-01-09 18:04

from django.db import migrations
from datetime import timedelta


def set_duration_manual_none_to_zero(apps, schema_editor):
    Session = apps.get_model("tracker", "Session")
    for session in Session.objects.all():
        if session.duration_manual == None:
            session.duration_manual = timedelta(0)
            session.save()


def revert_set_duration_manual_none_to_zero(apps, schema_editor):
    Session = apps.get_model("tracker", "Session")
    for session in Session.objects.all():
        if session.duration_manual == timedelta(0):
            session.duration_manual = None
            session.save()


class Migration(migrations.Migration):

    dependencies = [
        ("tracker", "0005_auto_20230109_1843"),
    ]

    operations = [
        migrations.RunPython(
            set_duration_manual_none_to_zero,
            revert_set_duration_manual_none_to_zero,
        )
    ]