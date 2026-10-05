"""Generate TypeScript contracts from registered elements and Python vocabularies."""

from pathlib import Path
from typing import TypeAliasType, get_args, get_type_hints

from django.conf import settings
from django.core.management.base import BaseCommand

# Importing the components package triggers element registration at import time.
import common.components
import common.criteria
from common.components.custom_elements import TypedDictClass, render_props_module
from common.components.date_range_picker import (
    CALENDAR_DAY_CLASSES,
    CALENDAR_TRACK_CLASSES,
    CALENDAR_WEEKDAY_CLASS,
    CalendarDayVariant,
    CalendarTrackVariant,
)
from common.components.form_dialog import (
    FORM_DIALOG_ATTRIBUTE,
    FORM_DIALOG_CHROME_BY_MARKER,
    FORM_DIALOG_ID_ATTRIBUTES,
    FORM_DIALOG_ID_LIST_ATTRIBUTES,
    FORM_DIALOG_PARTS,
    DialogAnswer,
    FormDialogChrome,
    FormDialogPart,
)
from common.components.modal import MODAL_ATTRIBUTES, ModalAttributeRole
from common.components.primitives import (
    SHAPE_CLASSES,
    YEAR_PICKER_CLASSES,
    ButtonShape,
)
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
from common.date_time_presentation import DateTimePresentationConfig
from common.form_dialog import FORM_DIALOG_HEADER
from games.models import ADDON_KINDS
from games.views.catalog_section import (
    CATALOG_NAME_KINDS,
    NAME_SLOT,
    CatalogNameKind,
)
from timetracker.config import SETTING_SOURCE_CHOICES
from timetracker.settings_commands import SETTING_NAMESPACE_CHOICES
from timetracker.settings_registry import THEME_CHOICES


def _union_members(union: object) -> list[TypedDictClass]:
    """A union's members, nested aliases unfolded."""
    members: list[TypedDictClass] = []
    for member in get_args(union):
        if isinstance(member, TypeAliasType):
            members.extend(_union_members(member.__value__))
        else:
            members.append(member)
    return members


def form_dialog_module() -> str:
    """The form dialog's wire: answers, header, markers."""
    return render_filter_metadata_module(
        _union_members(DialogAnswer.__value__),
        constants=[
            TsConstant("FORM_DIALOG_HEADER", str, FORM_DIALOG_HEADER),
            TsConstant("FORM_DIALOG_ATTRIBUTE", str, FORM_DIALOG_ATTRIBUTE),
            TsConstant(
                "FORM_DIALOG_CHROME_BY_MARKER",
                dict[str, FormDialogChrome],
                dict(FORM_DIALOG_CHROME_BY_MARKER),
            ),
            TsConstant(
                "FORM_DIALOG_PARTS",
                dict[FormDialogPart, str],
                dict(FORM_DIALOG_PARTS),
            ),
            TsConstant(
                "FORM_DIALOG_ID_ATTRIBUTES", list[str], list(FORM_DIALOG_ID_ATTRIBUTES)
            ),
            TsConstant(
                "FORM_DIALOG_ID_LIST_ATTRIBUTES",
                list[str],
                list(FORM_DIALOG_ID_LIST_ATTRIBUTES),
            ),
        ],
    )


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
                        "CALENDAR_DAY_CLASSES",
                        dict[CalendarDayVariant, str],
                        CALENDAR_DAY_CLASSES,
                    ),
                    TsConstant(
                        "CALENDAR_TRACK_CLASSES",
                        dict[CalendarTrackVariant, str],
                        CALENDAR_TRACK_CLASSES,
                    ),
                    TsConstant("CALENDAR_WEEKDAY_CLASS", str, CALENDAR_WEEKDAY_CLASS),
                    TsConstant(
                        "YEAR_PICKER_CLASSES", dict[str, str], YEAR_PICKER_CLASSES
                    ),
                    # Typed keys, so a rename fails `tsc` rather than
                    # resolving to `undefined`: a lost "full" would square
                    # every day cell in both pickers.
                    TsConstant(
                        "BUTTON_SHAPE_CLASSES", dict[ButtonShape, str], SHAPE_CLASSES
                    ),
                ],
            ),
            # The modal layer reads and stamps these.
            output_dir / "modal-attributes.ts": render_filter_metadata_module(
                [],
                constants=[
                    TsConstant(
                        "MODAL_ATTRIBUTES",
                        dict[ModalAttributeRole, str],
                        dict(MODAL_ATTRIBUTES),
                    ),
                ],
            ),
            # The form dialog's wire contract.
            output_dir / "form-dialog.ts": form_dialog_module(),
            # `<game-addon>` shows the parent for these.
            output_dir / "game-kinds.ts": render_filter_metadata_module(
                [],
                constants=[
                    TsConstant("ADDON_KINDS", list[str], sorted(ADDON_KINDS)),
                ],
            ),
            # `<catalog-editor>` fills the server's name patterns.
            output_dir / "catalog-names.ts": render_filter_metadata_module(
                [],
                constants=[
                    TsConstant("CATALOG_NAME_SLOT", str, NAME_SLOT),
                    TsConstant(
                        "CATALOG_NAME_KINDS",
                        list[CatalogNameKind],
                        list(CATALOG_NAME_KINDS),
                    ),
                ],
            ),
        }
        for target, content in targets.items():
            target.write_text(content, encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"Wrote {target}"))
