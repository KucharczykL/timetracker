# from datetime import timedelta

import contextlib

from django.apps import AppConfig
from django.core.management import call_command
from django.db import connections
from django.db.backends.signals import connection_created
from django.db.models.signals import post_migrate, pre_migrate

from games.projection_writers import ProjectionWriter, install_guard, projection_writes
from timetracker.database import (
    apply_statement_limit,
    validate_default_connection,
)

# from django.utils.timezone import now

#: The migrate door, open from pre_migrate until post_migrate.
_migrate_door = contextlib.ExitStack()


class GamesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "games"

    def ready(self):
        #: Import side effects: signals, projectors, checks.
        from games import checks, projectors, signals  # noqa: F401

        connection_created.connect(
            validate_default_connection,
            dispatch_uid="timetracker.validate_postgres_contract",
        )
        connection_created.connect(
            apply_statement_limit,
            dispatch_uid="timetracker.statement_limit",
        )
        connection_created.connect(
            _install_projection_guard,
            dispatch_uid="games.projection_guard",
        )
        for connection in connections.all(initialized_only=True):
            install_guard(connection)
        pre_migrate.connect(_open_migrate_door, sender=self)
        post_migrate.connect(_close_migrate_door, sender=self)
        post_migrate.connect(schedule_tasks, sender=self)


def _install_projection_guard(connection, **kwargs):
    install_guard(connection)


def _open_migrate_door(sender, **kwargs):
    _migrate_door.enter_context(projection_writes(ProjectionWriter.MIGRATE))


def _close_migrate_door(sender, **kwargs):
    _migrate_door.close()


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

    from games.models import ExchangeRate

    if not ExchangeRate.objects.exists():
        print("ExchangeRate table is empty. Loading fixture...")
        call_command("loaddata", "exchangerates.yaml")
