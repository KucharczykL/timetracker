from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand
from django_q.models import OrmQ, Schedule, Task


class Command(BaseCommand):
    help = (
        "Remove copied production artifacts from a staging database seeded "
        "from a production snapshot: clears authenticated sessions and the "
        "django-q schedule/queue/results so staging does not share prod's "
        "session cookies or independently run scheduled tasks."
    )

    def handle(self, *args, **kwargs):
        sessions_deleted, _ = Session.objects.all().delete()
        schedules_deleted, _ = Schedule.objects.all().delete()
        tasks_deleted, _ = Task.objects.all().delete()
        queued_deleted, _ = OrmQ.objects.all().delete()

        self.stdout.write(
            self.style.SUCCESS(
                "Scrubbed staging database: "
                f"{sessions_deleted} session(s), "
                f"{schedules_deleted} schedule(s), "
                f"{tasks_deleted} task result(s), "
                f"{queued_deleted} queued task(s) removed."
            )
        )
