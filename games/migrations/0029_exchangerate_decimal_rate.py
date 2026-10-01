from decimal import Decimal

from django.db import migrations, models

#: Twelve places, as the model states.
PLACES = Decimal("1e-12")


def decimal_rate(rate: float) -> Decimal:
    """The float's shortest spelling, at twelve places."""
    return Decimal(repr(rate)).quantize(PLACES)


def copy_forward(apps, schema_editor):
    ExchangeRate = apps.get_model("games", "ExchangeRate")
    rows = list(ExchangeRate.objects.all())
    for row in rows:
        row.rate_decimal = decimal_rate(row.rate)
    ExchangeRate.objects.bulk_update(rows, ["rate_decimal"])


def copy_backward(apps, schema_editor):
    ExchangeRate = apps.get_model("games", "ExchangeRate")
    rows = list(ExchangeRate.objects.all())
    for row in rows:
        row.rate = float(row.rate_decimal)
    ExchangeRate.objects.bulk_update(rows, ["rate"])


class Migration(migrations.Migration):
    dependencies = [
        ("games", "0028_purchase_refund"),
    ]

    operations = [
        migrations.AlterField(
            model_name="exchangerate",
            name="rate",
            field=models.FloatField(null=True),
        ),
        migrations.AddField(
            model_name="exchangerate",
            name="rate_decimal",
            field=models.DecimalField(decimal_places=12, max_digits=24, null=True),
        ),
        migrations.RunPython(copy_forward, copy_backward),
        migrations.RemoveField(model_name="exchangerate", name="rate"),
        migrations.RenameField(
            model_name="exchangerate", old_name="rate_decimal", new_name="rate"
        ),
        migrations.AlterField(
            model_name="exchangerate",
            name="rate",
            field=models.DecimalField(decimal_places=12, max_digits=24),
        ),
    ]
