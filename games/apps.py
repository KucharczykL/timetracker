from datetime import timedelta

from django.apps import AppConfig
from django.core.management import call_command
from django.db.models.signals import post_migrate
from django.utils.timezone import now


class GamesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "games"

    def ready(self):
        import games.signals  # noqa: F401

        post_migrate.connect(schedule_tasks, sender=self)


def schedule_tasks(sender, **kwargs):
    from django_q.models import Schedule
    from django_q.tasks import schedule

    if not Schedule.objects.filter(name="Update converted prices").exists():
        schedule(
            "games.tasks.convert_prices",
            name="Update converted prices",
            schedule_type=Schedule.MINUTES,
            next_run=now() + timedelta(seconds=30),
        )

    if not Schedule.objects.filter(name="Update price per game").exists():
        schedule(
            "games.tasks.calculate_price_per_game",
            name="Update price per game",
            schedule_type=Schedule.MINUTES,
            next_run=now() + timedelta(seconds=30),
        )

    from games.models import ExchangeRate

    if not ExchangeRate.objects.exists():
        print("ExchangeRate table is empty. Loading fixture...")
        call_command("loaddata", "exchangerates.yaml")
