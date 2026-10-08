import secrets

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand

from games.models import Game

type Username = str

DEFAULT_SUPERUSER: Username = "admin"
OLD_DEFAULT_PASSWORD = "admin"
PASSWORD_BYTES = 16


class Command(BaseCommand):
    help = (
        "Run the container's one-shot startup work — migrate, plus whichever of "
        "the staging scrub, sample-data seed and default superuser the "
        "entrypoint asks for — in a single Django process."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--scrub-staging",
            action="store_true",
            help="Drop sessions and the django-q schedule copied from a production snapshot.",
        )
        parser.add_argument(
            "--sample-data",
            action="store_true",
            help="Seed the demo fixture, but only while the games table is empty.",
        )
        parser.add_argument(
            "--default-superuser",
            action="store_true",
            help=(
                "Create an admin superuser with a random password, printed once, "
                "unless one already exists."
            ),
        )

    def handle(self, *args, **options):
        call_command("migrate")

        if options["scrub_staging"]:
            call_command("scrub_staging")

        should_load_sample = options["sample_data"] and not Game.objects.exists()
        should_create_default_user = options["default_superuser"] or should_load_sample

        if should_create_default_user:
            self._ensure_default_superuser()

        if should_load_sample:
            call_command("load_sample_data", "--user", DEFAULT_SUPERUSER)
            self.stdout.write(self.style.SUCCESS("Loaded sample data."))

    def _ensure_default_superuser(self) -> None:
        user_model = get_user_model()
        existing = user_model.objects.filter(username=DEFAULT_SUPERUSER).first()
        if existing is None:
            password = secrets.token_urlsafe(PASSWORD_BYTES)
            user_model.objects.create_superuser(DEFAULT_SUPERUSER, "", password)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Created default superuser: {DEFAULT_SUPERUSER} / {password}"
                    " (not shown again)"
                )
            )
        elif not existing.is_superuser:
            self.stderr.write(
                self.style.WARNING(
                    f"User '{DEFAULT_SUPERUSER}' exists but is no superuser;"
                    " created none."
                )
            )
        elif existing.check_password(OLD_DEFAULT_PASSWORD):
            self.stderr.write(
                self.style.ERROR(
                    f"Superuser '{DEFAULT_SUPERUSER}' still has the old default"
                    f" password. Run: manage.py changepassword {DEFAULT_SUPERUSER}"
                )
            )
        else:
            self.stdout.write(
                f"Superuser '{DEFAULT_SUPERUSER}' exists; password unchanged"
                f" (manage.py changepassword {DEFAULT_SUPERUSER} resets it)."
            )
