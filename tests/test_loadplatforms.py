from django.core.management import call_command
from django.test import TestCase

from games.models import Platform


class LoadPlatformsTest(TestCase):
    def test_loads_fixture_platforms(self):
        call_command("loadplatforms")

        self.assertTrue(Platform.objects.filter(name="Steam").exists())
        self.assertTrue(Platform.objects.filter(name="Nintendo Switch").exists())

    def test_is_idempotent(self):
        call_command("loadplatforms")
        first_run_count = Platform.objects.count()
        self.assertGreater(first_run_count, 0)

        call_command("loadplatforms")

        self.assertEqual(Platform.objects.count(), first_run_count)

    def test_slugifies_icons(self):
        call_command("loadplatforms")

        self.assertEqual(Platform.objects.get(name="Steam").icon, "steam")
        self.assertEqual(
            Platform.objects.get(name="Epic Games Store").icon, "epic-games-store"
        )

    def test_preserves_user_edited_platform(self):
        existing = Platform.objects.create(
            name="Steam", group="Custom group", icon="custom-icon"
        )

        call_command("loadplatforms")

        self.assertEqual(Platform.objects.filter(name="Steam").count(), 1)
        existing.refresh_from_db()
        self.assertEqual(existing.group, "Custom group")
        self.assertEqual(existing.icon, "custom-icon")
