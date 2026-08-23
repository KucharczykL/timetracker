# from datetime import timedelta

from django.apps import AppConfig
from django.core.management import call_command
from django.db.backends.signals import connection_created
from django.db.models.signals import post_migrate

from timetracker.database import validate_default_connection

# from django.utils.timezone import now


class GamesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "games"

    def ready(self):
        #: Imported for their import side effects: signal receivers connect and
        #: projector families register. A projector nobody imported is a
        #: projection that silently never updates.
        from games import projectors, signals  # noqa: F401

        connection_created.connect(
            validate_default_connection,
            dispatch_uid="timetracker.validate_postgres_contract",
        )
        post_migrate.connect(schedule_tasks, sender=self)


def schedule_tasks(sender, **kwargs):
    # from django_q.models import Schedule
    # from django_q.tasks import schedule

    # if not Schedule.objects.filter(name="Update converted prices").exists():
    #     schedule(
    #         "games.tasks.convert_prices",
    #         name="Update converted prices",
    #         schedule_type=Schedule.MINUTES,
    #         next_run=now() + timedelta(seconds=30),
    #         catchup=False,
    #     )

    # if not Schedule.objects.filter(name="Update price per game").exists():
    #     schedule(
    #         "games.tasks.calculate_price_per_game",
    #         name="Update price per game",
    #         schedule_type=Schedule.MINUTES,
    #         next_run=now() + timedelta(seconds=30),
    #         catchup=False,
    #     )

    from games.models import ExchangeRate

    if not ExchangeRate.objects.exists():
        print("ExchangeRate table is empty. Loading fixture...")
        call_command("loaddata", "exchangerates.yaml")
