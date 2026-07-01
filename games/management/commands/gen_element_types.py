"""Write ts/generated/*.ts: element-props + filter-metadata contracts."""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

# Importing the components package triggers element registration at import time.
import common.components  # noqa: F401
from common.components.custom_elements import render_props_module
from common.components.ts_codegen import render_filter_metadata_module
from common.criteria import ComparableColumn, FieldMeta


class Command(BaseCommand):
    help = "Generate ts/generated/*.ts contracts from Python (props + filter metadata)."

    def handle(self, *args, **options) -> None:
        output_dir = Path(settings.BASE_DIR) / "ts" / "generated"
        output_dir.mkdir(parents=True, exist_ok=True)

        targets = {
            output_dir / "props.ts": render_props_module(),
            output_dir / "filter-metadata.ts": render_filter_metadata_module(
                [FieldMeta, ComparableColumn]
            ),
        }
        for target, content in targets.items():
            target.write_text(content, encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"Wrote {target}"))
