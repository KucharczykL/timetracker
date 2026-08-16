from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand

from games.models import Game


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
            help="Create an admin/admin superuser unless one already exists.",
        )

    def handle(self, *args, **options):
        call_command("migrate")

        if options["scrub_staging"]:
            call_command("scrub_staging")

        should_load_sample = options["sample_data"] and not Game.objects.exists()
        should_create_default_user = options["default_superuser"] or should_load_sample

        if should_create_default_user:
            user_model = get_user_model()
            if not user_model.objects.filter(username="admin").exists():
                user_model.objects.create_superuser("admin", "", "admin")
                self.stdout.write(
                    self.style.SUCCESS("Created default superuser: admin / admin")
                )

        if should_load_sample:
            call_command("load_sample_data", "--user", "admin")
            self.stdout.write(self.style.SUCCESS("Loaded sample data."))
