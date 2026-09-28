from django.core.management import call_command
from django.test import TestCase

from common.platform_icons import PLATFORM_ICONS
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

    def test_states_listed_icons(self):
        call_command("loadplatforms")

        self.assertEqual(Platform.objects.get(name="Epic Games Store").icon, "egs")
        self.assertEqual(Platform.objects.get(name="Nintendo 3DS").icon, "nintendo")
        self.assertLessEqual(
            set(Platform.objects.values_list("icon", flat=True)), set(PLATFORM_ICONS)
        )

    def test_preserves_user_edited_platform(self):
        existing = Platform.objects.create(
            name="Steam", group="Custom group", icon="gog"
        )

        call_command("loadplatforms")

        self.assertEqual(Platform.objects.filter(name="Steam").count(), 1)
        existing.refresh_from_db()
        self.assertEqual(existing.group, "Custom group")
        self.assertEqual(existing.icon, "gog")

    def test_an_unlisted_fixture_icon_names_its_platform(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from unittest import mock

        from django.core.management.base import CommandError

        with TemporaryDirectory() as directory:
            fixture = Path(directory) / "platforms.yaml"
            fixture.write_text(
                "- model: games.Platform\n  fields:\n    name: Amiga\n    icon: amiga\n"
            )
            with (
                mock.patch(
                    "games.management.commands.loadplatforms.FIXTURE_PATH", fixture
                ),
                self.assertRaisesMessage(CommandError, "Fixture platform 'Amiga'"),
            ):
                call_command("loadplatforms")
