"""Generate TypeScript contracts from registered elements and Python vocabularies."""

from pathlib import Path
from typing import get_type_hints

from django.conf import settings
from django.core.management.base import BaseCommand

# Importing the components package triggers element registration at import time.
import common.components  # noqa: F401
import common.criteria
from common.components.date_range_picker import (
    CALENDAR_DAY_CLASSES,
    CALENDAR_TRACK_CLASSES,
    CALENDAR_WEEKDAY_CLASS,
)
from common.date_time_presentation import DateTimePresentationConfig
from common.components.custom_elements import render_props_module
from common.components.ts_codegen import (
    ChoiceVocab,
    TsConstant,
    render_choice_vocabularies,
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
from timetracker.config import SETTING_SOURCE_CHOICES
from timetracker.settings_commands import SETTING_NAMESPACE_CHOICES
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
            output_dir / "settings-vocabulary.ts": render_choice_vocabularies(
                [
                    ChoiceVocab(
                        type_name="SettingNamespace",
                        values_name="SETTING_NAMESPACES",
                        labels_name="SETTING_NAMESPACE_LABELS",
                        choices=SETTING_NAMESPACE_CHOICES,
                    ),
                    ChoiceVocab(
                        type_name="SettingSource",
                        values_name="SETTING_SOURCES",
                        labels_name="SETTING_SOURCE_LABELS",
                        choices=SETTING_SOURCE_CHOICES,
                    ),
                ]
            ),
            output_dir / "date-time-presentation.ts": render_filter_metadata_module(
                [DateTimePresentationConfig]
            ),
            # The calendar's day-cell look, composed in Python from
            # ControlButton (common/components/date_range_picker.py). The 42
            # cells are cloned client-side, so without this the classes would
            # have to be hand-mirrored in TypeScript — which is how they drifted
            # into square corners and a sub-minimum hit area.
            output_dir / "calendar-classes.ts": render_filter_metadata_module(
                [],
                constants=[
                    TsConstant(
                        "CALENDAR_DAY_CLASSES", dict[str, str], CALENDAR_DAY_CLASSES
                    ),
                    TsConstant(
                        "CALENDAR_TRACK_CLASSES", dict[str, str], CALENDAR_TRACK_CLASSES
                    ),
                    TsConstant("CALENDAR_WEEKDAY_CLASS", str, CALENDAR_WEEKDAY_CLASS),
                ],
            ),
        }
        for target, content in targets.items():
            target.write_text(content, encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"Wrote {target}"))
