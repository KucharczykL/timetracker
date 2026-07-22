"""Generate TypeScript contracts from registered elements and Python vocabularies."""

from pathlib import Path
from typing import get_type_hints

from django.conf import settings
from django.core.management.base import BaseCommand

# Importing the components package triggers element registration at import time.
import common.components  # noqa: F401
import common.criteria
from common.date_time_presentation import DateTimePresentationConfig
from common.components.custom_elements import render_props_module
from common.components.ts_codegen import (
    TsConstant,
    render_choice_vocabulary,
    render_filter_metadata_module,
)
from common.criteria import (
    SPACE_GROUPS,
    ComparableColumn,
    FieldMeta,
    Modifier,
    ModifierToken,
)
from timetracker.settings_registry import THEME_CHOICES


class Command(BaseCommand):
    help = "Generate ts/generated/*.ts contracts from registered Python sources."

    def handle(self, *args, **options) -> None:
        output_dir = Path(settings.BASE_DIR) / "ts" / "generated"
        output_dir.mkdir(parents=True, exist_ok=True)

        # The comparison-space vocabulary (issue #284), published as typed consts
        # so the field-comparison widget cannot drift from the Python tables.
        # SPACE_GROUPS' type comes from its annotation in common/criteria.py
        # (via get_type_hints) — one source for both the value and its TS type.
        filter_constants = [
            TsConstant(
                "SPACE_GROUPS",
                get_type_hints(common.criteria)["SPACE_GROUPS"],
                SPACE_GROUPS,
            ),
            TsConstant(
                "SPACE_ORDERED_MODIFIERS",
                list[ModifierToken],
                Modifier.for_ordered_field_comparisons(),
            ),
        ]

        targets = {
            output_dir / "props.ts": render_props_module(),
            output_dir / "filter-metadata.ts": render_filter_metadata_module(
                [FieldMeta, ComparableColumn], constants=filter_constants
            ),
            output_dir / "theme-preferences.ts": render_choice_vocabulary(
                type_name="ThemePreference",
                values_name="THEME_PREFERENCES",
                labels_name="THEME_LABELS",
                choices=THEME_CHOICES,
            ),
            output_dir / "date-time-presentation.ts": render_filter_metadata_module(
                [DateTimePresentationConfig]
            ),
        }
        for target, content in targets.items():
            target.write_text(content, encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"Wrote {target}"))
