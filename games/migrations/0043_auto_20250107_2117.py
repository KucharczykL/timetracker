# Generated by Django 5.1.3 on 2025-01-07 20:17

from django.db import migrations


def migrate_edition_to_editions_temp(apps, schema_editor):
    Purchase = apps.get_model("games", "Purchase")
    for purchase in Purchase.objects.all():
        if purchase.edition:
            print(
                f"Migrating Purchase {purchase.id} with Edition {purchase.edition.id}"
            )
            purchase.editions_temp.add(purchase.edition)
            print(purchase.editions_temp.all())
            purchase.save()
        else:
            print(f"No edition found for Purchase {purchase.id}")


class Migration(migrations.Migration):
    dependencies = [
        ("games", "0042_purchase_editions_temp"),
    ]

    operations = [
        migrations.RunPython(migrate_edition_to_editions_temp),
    ]
