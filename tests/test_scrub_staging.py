from datetime import timedelta

from django.contrib.sessions.models import Session as DjangoSession
from django.core.management import call_command
from django.test import TestCase
from django.utils.timezone import now
from django_q.models import Schedule


class ScrubStagingTest(TestCase):
    def test_scrub_removes_sessions_and_schedules(self):
        DjangoSession.objects.create(
            session_key="copied-from-prod",
            session_data="",
            expire_date=now() + timedelta(days=1),
        )
        Schedule.objects.create(
            func="games.tasks.convert_prices",
            name="Update converted prices",
            schedule_type=Schedule.MINUTES,
        )

        self.assertEqual(DjangoSession.objects.count(), 1)
        self.assertEqual(Schedule.objects.count(), 1)

        call_command("scrub_staging")

        self.assertEqual(DjangoSession.objects.count(), 0)
        self.assertEqual(Schedule.objects.count(), 0)

    def test_scrub_is_safe_on_empty_database(self):
        # Should not raise when there is nothing to remove (fresh staging DB).
        call_command("scrub_staging")

        self.assertEqual(DjangoSession.objects.count(), 0)
        self.assertEqual(Schedule.objects.count(), 0)
