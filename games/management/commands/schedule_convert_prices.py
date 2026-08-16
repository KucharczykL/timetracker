from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils.timezone import now
from django_q.models import Schedule
from django_q.tasks import schedule


class Command(BaseCommand):
    help = "Ensure the daily recovery schedule for library price conversions exists"

    def handle(self, *args, **kwargs):
        name = "Recover library price conversions"
        Schedule.objects.filter(func="games.tasks.convert_prices").delete()
        Schedule.objects.filter(name="Update converted prices").delete()
        if not Schedule.objects.filter(name=name).exists():
            schedule(
                "games.tasks.recover_library_price_conversions",
                name=name,
                schedule_type=Schedule.DAILY,
                next_run=now() + timedelta(seconds=30),
            )
            self.stdout.write(
                self.style.SUCCESS("Scheduled daily library price-conversion recovery.")
            )
        else:
            self.stdout.write(self.style.WARNING("Recovery task is already scheduled."))
