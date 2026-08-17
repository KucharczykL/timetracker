import django.db.models.deletion
from django.db import migrations, models
from django.db.models import F, Q
from django.db.models.functions import Lower, Trim
from django.utils import timezone


class Migration(migrations.Migration):
    dependencies = [("games", "0003_userlibrary")]
    operations = [
        migrations.AddField(
            model_name="game",
            name="library",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="games",
                to="games.userlibrary",
            ),
        ),
        migrations.AddField(
            model_name="purchase",
            name="library",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="purchases",
                to="games.userlibrary",
            ),
        ),
        migrations.AddField(
            model_name="device",
            name="library",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="devices",
                to="games.userlibrary",
            ),
        ),
        migrations.AddField(
            model_name="filterpreset",
            name="library",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="filter_presets",
                to="games.userlibrary",
            ),
        ),
        migrations.AddField(
            model_name="platform",
            name="library",
            field=models.ForeignKey(
                blank=True,
                default=None,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="platforms",
                to="games.userlibrary",
            ),
        ),
        migrations.CreateModel(
            name="UserLibraryPreferences",
            fields=[
                (
                    "library",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        related_name="preferences",
                        serialize=False,
                        to="games.userlibrary",
                    ),
                ),
                (
                    "default_device",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="games.device",
                    ),
                ),
                ("updated_at", models.DateTimeField(default=timezone.now)),
            ],
        ),
        migrations.CreateModel(
            name="PurchaseConversionState",
            fields=[
                (
                    "library",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        related_name="purchase_conversion_state",
                        serialize=False,
                        to="games.userlibrary",
                    ),
                ),
                (
                    "requested_version",
                    models.PositiveBigIntegerField(default=0),
                ),
                (
                    "requested_currency",
                    models.CharField(blank=True, default="", max_length=3),
                ),
                (
                    "published_version",
                    models.PositiveBigIntegerField(default=0),
                ),
                (
                    "published_currency",
                    models.CharField(blank=True, default="", max_length=3),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("running", "Running"),
                            ("failed", "Failed"),
                            ("complete", "Complete"),
                        ],
                        default="complete",
                        max_length=10,
                    ),
                ),
                (
                    "retry_at",
                    models.DateTimeField(blank=True, default=None, null=True),
                ),
                ("last_error", models.TextField(blank=True, default="")),
            ],
        ),
        migrations.AddField(
            model_name="userpreferences",
            name="default_purchase_currency",
            field=models.CharField(blank=True, default=None, max_length=3, null=True),
        ),
        migrations.AddField(
            model_name="userpreferences",
            name="default_display_currency",
            field=models.CharField(blank=True, default=None, max_length=3, null=True),
        ),
        migrations.RemoveField(
            model_name="userpreferences",
            name="default_currency",
        ),
        migrations.RemoveField(
            model_name="userpreferences",
            name="default_device",
        ),
        migrations.RunSQL(
            sql="SET CONSTRAINTS ALL IMMEDIATE",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.AlterField(
            model_name="game",
            name="library",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="games",
                to="games.userlibrary",
            ),
        ),
        migrations.AlterField(
            model_name="purchase",
            name="library",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="purchases",
                to="games.userlibrary",
            ),
        ),
        migrations.AlterField(
            model_name="device",
            name="library",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="devices",
                to="games.userlibrary",
            ),
        ),
        migrations.AlterField(
            model_name="filterpreset",
            name="library",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="filter_presets",
                to="games.userlibrary",
            ),
        ),
        migrations.AlterField(
            model_name="session",
            name="game",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="sessions",
                to="games.game",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="game",
            name="unique_platformless_game_name_year",
        ),
        migrations.AlterUniqueTogether(
            name="game",
            unique_together={("library", "name", "platform", "year_released")},
        ),
        migrations.AddConstraint(
            model_name="game",
            constraint=models.UniqueConstraint(
                condition=Q(platform__isnull=True),
                fields=("library", "name", "year_released"),
                name="unique_library_platformless_game_name_year",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="filterpreset",
            name="unique_user_mode_name_preset",
        ),
        migrations.RemoveField(
            model_name="filterpreset",
            name="user",
        ),
        migrations.AddConstraint(
            model_name="filterpreset",
            constraint=models.UniqueConstraint(
                fields=("library", "mode", "name"),
                name="unique_library_mode_name_preset",
            ),
        ),
        migrations.AddConstraint(
            model_name="platform",
            constraint=models.UniqueConstraint(
                Lower(Trim("name")),
                Lower(Trim("group")),
                condition=Q(library__isnull=True),
                name="unique_shared_platform_normalized_name_group",
            ),
        ),
        migrations.AddConstraint(
            model_name="platform",
            constraint=models.UniqueConstraint(
                F("library"),
                Lower(Trim("name")),
                Lower(Trim("group")),
                condition=Q(library__isnull=False),
                name="unique_private_platform_normalized_name_group",
            ),
        ),
    ]
