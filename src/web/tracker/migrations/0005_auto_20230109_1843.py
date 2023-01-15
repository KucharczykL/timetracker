# Generated by Django 4.1.5 on 2023-01-09 17:43

from datetime import timedelta

from django.db import migrations


def set_duration_calculated_none_to_zero(apps, schema_editor):
    Session = apps.get_model("tracker", "Session")
    for session in Session.objects.all():
        if session.duration_calculated == None:
            session.duration_calculated = timedelta(0)
            session.save()


def revert_set_duration_calculated_none_to_zero(apps, schema_editor):
    Session = apps.get_model("tracker", "Session")
    for session in Session.objects.all():
        if session.duration_calculated == timedelta(0):
            session.duration_calculated = None
            session.save()


class Migration(migrations.Migration):

    dependencies = [
        ("tracker", "0004_alter_session_duration_manual"),
    ]

    operations = [
        migrations.RunPython(
            set_duration_calculated_none_to_zero,
            revert_set_duration_calculated_none_to_zero,
        )
    ]
