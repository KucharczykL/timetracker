from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils.timezone import now
from django_q.models import Schedule
from django_q.tasks import schedule


class Command(BaseCommand):
    help = "Manually schedule the next update_converted_prices task"

    def handle(self, *args, **kwargs):
        if not Schedule.objects.filter(name="Update converted prices").exists():
            schedule(
                "games.tasks.convert_prices",
                name="Update converted prices",
                schedule_type=Schedule.MINUTES,
                next_run=now() + timedelta(seconds=30),
            )
            self.stdout.write(
                self.style.SUCCESS("Scheduled the update_converted_prices task.")
            )
        else:
            self.stdout.write(self.style.WARNING("Task is already scheduled."))
