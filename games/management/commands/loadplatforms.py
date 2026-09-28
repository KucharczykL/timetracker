from pathlib import Path

from django.core import serializers
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from games.models import Platform

FIXTURE_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "platforms.yaml"


class Command(BaseCommand):
    help = (
        "Load the platform fixture idempotently: platforms whose name already "
        "exists are skipped, new ones are saved through Platform.save(), which refuses an unlisted icon."
    )

    def handle(self, *args, **options):
        created_count = 0
        skipped_count = 0
        with FIXTURE_PATH.open() as fixture_file:
            for deserialized in serializers.deserialize("yaml", fixture_file):
                platform = deserialized.object
                if not isinstance(platform, Platform):
                    raise CommandError(
                        f"Unexpected model in platform fixture: {platform!r}"
                    )
                if Platform.objects.filter(name=platform.name).exists():
                    skipped_count += 1
                    continue
                try:
                    platform.save()
                except ValidationError as refusal:
                    raise CommandError(
                        f"Fixture platform {platform.name!r}: {refusal.messages[0]}"
                    ) from refusal
                created_count += 1
        self.stdout.write(
            self.style.SUCCESS(
                f"Platforms: {created_count} created, {skipped_count} already existed."
            )
        )
