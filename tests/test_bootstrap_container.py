"""The container's one-shot startup command.

The entrypoint translates its env flags into arguments, so every branch here is
reachable only through one of them — a container that asks for nothing gets a
migrate and nothing else.
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from games.models import Game


def _run(*args) -> list[tuple]:
    """Run the command with `call_command` recorded; returns the nested calls."""
    with patch(
        "games.management.commands.bootstrap_container.call_command"
    ) as call_command_mock:
        call_command("bootstrap_container", *args, verbosity=0)
    return [(call.args[0], call.args[1:]) for call in call_command_mock.call_args_list]


class BootstrapContainerTest(TestCase):
    def test_migrates_and_nothing_else_without_flags(self):
        self.assertEqual(_run(), [("migrate", ())])

    def test_scrub_staging_only_on_request(self):
        self.assertIn(("scrub_staging", ()), _run("--scrub-staging"))

    def test_sample_data_loads_into_an_empty_database(self):
        self.assertIn(("loaddata", ("sample.yaml.gz",)), _run("--sample-data"))

    def test_sample_data_skipped_when_games_exist(self):
        Game.objects.create(name="Already Seeded")
        self.assertNotIn(
            ("loaddata", ("sample.yaml.gz",)),
            _run("--sample-data"),
        )

    def test_default_superuser_created_once(self):
        user_model = get_user_model()

        _run("--default-superuser")
        admin = user_model.objects.get(username="admin")
        self.assertTrue(admin.is_superuser)

        # A restarted container must not trip over the user it made last time.
        _run("--default-superuser")
        self.assertEqual(user_model.objects.filter(username="admin").count(), 1)

    def test_no_superuser_without_the_flag(self):
        _run()
        self.assertFalse(get_user_model().objects.filter(username="admin").exists())
