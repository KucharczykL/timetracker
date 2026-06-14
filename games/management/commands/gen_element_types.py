"""Write ts/generated/props.ts from the registered custom-element specs."""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

# Importing the components package triggers element registration at import time.
import common.components  # noqa: F401
from common.components.custom_elements import render_props_module


class Command(BaseCommand):
    help = "Generate ts/generated/props.ts from registered custom elements."

    def handle(self, *args, **options) -> None:
        output_dir = Path(settings.BASE_DIR) / "ts" / "generated"
        output_dir.mkdir(parents=True, exist_ok=True)
        target = output_dir / "props.ts"
        target.write_text(render_props_module(), encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"Wrote {target}"))
