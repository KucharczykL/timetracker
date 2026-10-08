"""The container's one-shot startup command.

The entrypoint translates its env flags into arguments, so every branch here is
reachable only through one of them — a container that asks for nothing gets a
migrate and the stale content type sweep, nothing else.
"""

import re
from io import StringIO
from typing import NamedTuple
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, transaction
from django.test import TestCase

from games.management.commands.bootstrap_container import (
    DEFAULT_SUPERUSER,
    OLD_DEFAULT_PASSWORD,
)
from games.models import Game

type CommandName = str  # e.g. "migrate"


class NestedCall(NamedTuple):
    command: CommandName
    args: tuple[object, ...]


def _run(
    *args: str, stdout: StringIO | None = None, stderr: StringIO | None = None
) -> list[NestedCall]:
    """Run the command with `call_command` recorded; returns the nested calls."""
    with patch(
        "games.management.commands.bootstrap_container.call_command"
    ) as call_command_mock:
        call_command(
            "bootstrap_container", *args, verbosity=0, stdout=stdout, stderr=stderr
        )
    return [
        NestedCall(call.args[0], call.args[1:])
        for call in call_command_mock.call_args_list
    ]


def _printed_password(output: StringIO) -> str | None:
    match = re.search(rf"{re.escape(DEFAULT_SUPERUSER)} / (\S+)", output.getvalue())
    return match.group(1) if match else None


class BootstrapContainerTest(TestCase):
    def test_migrates_and_sweeps_and_nothing_else_without_flags(self):
        self.assertEqual(
            _run(),
            [("migrate", ()), ("remove_stale_contenttypes", ("--no-input",))],
        )

    def test_a_dropped_models_content_type_and_grants_go(self):
        stale = ContentType.objects.create(app_label="games", model="droppedmodel")
        permission = Permission.objects.create(
            content_type=stale, codename="view_droppedmodel", name="Can view"
        )
        user = get_user_model().objects.create_user(username="granted")
        user.user_permissions.add(permission)
        Group.objects.create(name="granted").permissions.add(permission)
        output = StringIO()

        call_command("bootstrap_container", verbosity=0, stdout=output)

        self.assertFalse(ContentType.objects.filter(pk=stale.pk).exists())
        self.assertFalse(Permission.objects.filter(pk=permission.pk).exists())
        self.assertIn("games | droppedmodel", output.getvalue())

    def test_live_models_and_uninstalled_apps_keep_their_rows(self):
        uninstalled = ContentType.objects.create(
            app_label="notinstalled", model="thing"
        )
        Permission.objects.create(
            content_type=uninstalled, codename="view_thing", name="Can view"
        )
        content_type_count = ContentType.objects.count()
        permission_count = Permission.objects.count()

        call_command("bootstrap_container", verbosity=0, stdout=StringIO())
        call_command("bootstrap_container", verbosity=0, stdout=StringIO())

        self.assertEqual(ContentType.objects.count(), content_type_count)
        self.assertEqual(Permission.objects.count(), permission_count)
        self.assertTrue(
            Permission.objects.filter(
                content_type__app_label="games", codename="view_game"
            ).exists()
        )

    def test_a_foreign_key_from_outside_the_apps_stops_startup(self):
        stale = ContentType.objects.create(app_label="games", model="droppedmodel")
        with connection.cursor() as cursor:
            cursor.execute(
                "CREATE TABLE leftover_log (content_type_id integer"
                " REFERENCES django_content_type (id))"
            )
            cursor.execute("INSERT INTO leftover_log VALUES (%s)", [stale.pk])

        with (
            transaction.atomic(),
            self.assertRaisesMessage(CommandError, "leftover_log"),
        ):
            call_command("bootstrap_container", verbosity=0, stdout=StringIO())

    def test_scrub_staging_only_on_request(self):
        self.assertIn(("scrub_staging", ()), _run("--scrub-staging"))

    def test_sample_data_loads_into_an_empty_database(self):
        self.assertIn(
            ("load_sample_data", ("--user", DEFAULT_SUPERUSER)),
            _run("--sample-data"),
        )
        self.assertTrue(
            get_user_model().objects.get(username=DEFAULT_SUPERUSER).is_superuser
        )

    def test_sample_data_skipped_when_games_exist(self):
        user = get_user_model().objects.create_user(username="existing")
        Game.objects.create(library=user.library, name="Already Seeded")
        self.assertNotIn(
            ("load_sample_data", ("--user", DEFAULT_SUPERUSER)),
            _run("--sample-data"),
        )

    def test_default_superuser_created_once(self):
        user_model = get_user_model()

        _run("--default-superuser")
        admin = user_model.objects.get(username=DEFAULT_SUPERUSER)
        self.assertTrue(admin.is_superuser)

        # A restarted container must not trip over the user it made last time.
        _run("--default-superuser")
        self.assertEqual(
            user_model.objects.filter(username=DEFAULT_SUPERUSER).count(), 1
        )

    def test_default_superuser_password_is_random_and_printed(self):
        output = StringIO()
        with patch(
            "games.management.commands.bootstrap_container.secrets.token_urlsafe",
            return_value="generated-token",
        ) as token_mock:
            _run("--default-superuser", stdout=output)
        admin = get_user_model().objects.get(username=DEFAULT_SUPERUSER)

        token_mock.assert_called_once()
        self.assertEqual(_printed_password(output), "generated-token")
        self.assertTrue(admin.check_password("generated-token"))

    def test_sample_data_superuser_gets_a_printed_password(self):
        output = StringIO()
        _run("--sample-data", stdout=output)
        admin = get_user_model().objects.get(username=DEFAULT_SUPERUSER)

        printed = _printed_password(output)
        self.assertIsNotNone(printed, output.getvalue())
        self.assertTrue(admin.check_password(printed))
        self.assertFalse(admin.check_password(OLD_DEFAULT_PASSWORD))

    def test_rerun_keeps_the_password_and_prints_none(self):
        first = StringIO()
        _run("--default-superuser", stdout=first)
        password = _printed_password(first)

        second = StringIO()
        _run("--default-superuser", stdout=second)
        admin = get_user_model().objects.get(username=DEFAULT_SUPERUSER)

        self.assertTrue(admin.check_password(password))
        self.assertIsNone(_printed_password(second))
        self.assertIn("password unchanged", second.getvalue())

    def test_old_default_password_is_reported(self):
        get_user_model().objects.create_superuser(
            DEFAULT_SUPERUSER, "", OLD_DEFAULT_PASSWORD
        )
        errors = StringIO()
        _run("--default-superuser", stderr=errors)

        self.assertIn("changepassword", errors.getvalue())

    def test_existing_non_superuser_admin_is_reported(self):
        get_user_model().objects.create_user(username=DEFAULT_SUPERUSER)
        errors = StringIO()
        _run("--default-superuser", stderr=errors)

        self.assertIn("no superuser", errors.getvalue())
        self.assertFalse(
            get_user_model().objects.get(username=DEFAULT_SUPERUSER).is_superuser
        )

    def test_no_superuser_without_the_flag(self):
        _run()
        self.assertFalse(
            get_user_model().objects.filter(username=DEFAULT_SUPERUSER).exists()
        )
