"""Developer-only gallery for the settings UI kit from issue #384."""

import json

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.middleware.csrf import get_token
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from common.components import (
    Badge,
    BadgeTone,
    Checkbox,
    ContentContainer,
    Div,
    Element,
    FormFieldGroup,
    Input,
    Label,
    LiveSettingFields,
    MaskedSecretField,
    Option,
    PageHeading,
    Select,
    SettingFieldState,
    SettingSourceBadge,
    SettingsFieldColumns,
    SettingsFieldLayout,
    SettingsScaffold,
    SettingsSection,
)
from common.components.primitives import P
from common.layout import render_page
from games.forms import INPUT_CLASS, SELECT_CLASS, PrimitiveWidgetsMixin
from timetracker.settings_commands import SettingNamespace

_PREVIEW_KEYS = {
    "PREVIEW_ENABLED": "Preview enabled",
    "PREVIEW_DESTINATION": "Default destination",
    "PREVIEW_LIMIT": "Daily limit",
    "PREVIEW_DISPLAY_NAME": "Display name",
    "PREVIEW_APP_URL": "Application URL",
}
_SOURCES = ("user", "database", "env", "env_file", "dotenv", "ini", "default")
_BADGE_TONES: tuple[BadgeTone, ...] = (
    "brand",
    "neutral",
    "success",
    "warning",
    "danger",
)


class SettingsKitPreviewForm(PrimitiveWidgetsMixin, forms.Form):
    """Native controls used to exercise the shared settings renderer."""

    enabled = forms.BooleanField(
        required=False,
        initial=True,
        label="Enable preview behavior",
    )
    destination = forms.ChoiceField(
        choices=[("library", "Library"), ("statistics", "Statistics")],
        initial="library",
        label="Default destination",
    )
    limit = forms.IntegerField(
        required=False,
        initial=10,
        min_value=1,
        label="Daily limit",
    )
    display_name = forms.CharField(
        required=False,
        initial="Before",
        label="Display name",
    )
    pinned_url = forms.CharField(
        required=False,
        initial="https://example.test",
        label="Application URL",
    )


def _live_fields(request: HttpRequest):
    form = SettingsKitPreviewForm()
    groups = [
        FormFieldGroup(
            "Preferences",
            ("enabled", "destination", "limit", "display_name"),
            "Checkbox, select, number, and text controls all use the shared Django form path.",
            "preview-preference-fields",
        ),
        FormFieldGroup(
            "Managed setting",
            ("pinned_url",),
            "Locked settings are genuinely disabled, not merely styled as disabled.",
            "preview-managed-fields",
        ),
    ]
    states = {
        "enabled": SettingFieldState(
            "PREVIEW_ENABLED",
            "user",
            help_text="Toggle the checkbox to trigger a successful preview save.",
        ),
        "destination": SettingFieldState("PREVIEW_DESTINATION", "database"),
        "limit": SettingFieldState("PREVIEW_LIMIT", "default"),
        "display_name": SettingFieldState(
            "PREVIEW_DISPLAY_NAME",
            "user",
            help_text='Enter "reject" to exercise rollback and the error toast.',
        ),
        "pinned_url": SettingFieldState(
            "PREVIEW_APP_URL",
            "env",
            locked=True,
            reason="Change APP_URL in the environment and restart the application.",
        ),
    }
    patch_url = reverse(
        "games:settings_kit_preview_patch",
        kwargs={"key": "__key__"},
    )
    return LiveSettingFields(
        form,
        states=states,
        patch_url_template=patch_url,
        csrf=get_token(request),
        groups=groups,
        namespace=SettingNamespace.USER,
    )


def _source_gallery():
    return Div(
        class_="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3",
        data_source_badge_gallery="",
    )[
        *[
            Div(
                class_="flex min-h-control items-center justify-between gap-3 rounded-base border border-default p-3"
            )[
                P(class_="text-type-body text-heading")[source],
                SettingSourceBadge(
                    source,
                    id=f"preview-source-{source}-tooltip",
                    namespace=SettingNamespace.USER,
                ),
            ]
            for source in _SOURCES
        ],
        Div(
            class_="flex min-h-control items-center justify-between gap-3 rounded-base border border-default p-3"
        )[
            P(class_="text-type-body text-heading")["locked environment"],
            SettingSourceBadge(
                "env",
                locked=True,
                reason="Environment values override saved settings in this example.",
                id="preview-source-env-locked-tooltip",
                namespace=SettingNamespace.USER,
            ),
        ],
    ]


def _badge_gallery():
    return Div(
        class_="flex flex-wrap items-center gap-3",
        data_badge_tone_gallery="",
    )[*[Badge(tone.title(), tone=tone) for tone in _BADGE_TONES]]


def _preview_label_line(
    *,
    field_id: str,
    label: str,
    source: str,
    tooltip_id: str,
):
    return Div(class_="flex min-w-0 flex-wrap items-center gap-2")[
        Label(for_=field_id, class_="text-type-label text-heading")[label],
        SettingSourceBadge(source, id=tooltip_id, namespace=SettingNamespace.USER),
    ]


def _preview_checkbox_field(prefix: str):
    field_id = f"{prefix}-enabled"
    help_id = f"{field_id}-help"
    label_line = _preview_label_line(
        field_id=field_id,
        label="Enable preview behavior",
        source="user",
        tooltip_id=f"{field_id}-source-tooltip",
    )
    checkbox = Checkbox(
        name=field_id,
        checked=True,
        id_=field_id,
        aria_describedby=help_id,
        class_="shrink-0",
    )
    help_text = P(id_=help_id, class_="text-type-micro text-body")[
        "Toggle the checkbox to trigger a successful preview save."
    ]
    return Div(class_="flex min-w-0 flex-col gap-2", data_preview_checkbox_field="")[
        Div(class_="flex items-center justify-between gap-6")[
            label_line,
            checkbox,
        ],
        help_text,
    ]


def _preview_standard_field(prefix: str, *, kind: str):
    field_id = f"{prefix}-{kind}"
    if kind == "destination":
        label = "Default destination"
        source = "database"
        control = Select(
            id_=field_id,
            name=field_id,
            class_=SELECT_CLASS,
        )[
            Option(value="library", selected=True)["Library"],
            Option(value="statistics")["Statistics"],
        ]
    else:
        label = "Daily limit"
        source = "default"
        control = Input(
            id_=field_id,
            name=field_id,
            type="number",
            value="10",
            min="1",
            class_=INPUT_CLASS,
        )
    return Div(class_="flex min-w-0 flex-col gap-2")[
        _preview_label_line(
            field_id=field_id,
            label=label,
            source=source,
            tooltip_id=f"{field_id}-source-tooltip",
        ),
        control,
    ]


def _supported_form_layout(
    *, columns: SettingsFieldColumns, name: str, explanation: str
):
    label = f"{columns} column" + ("s" if columns != 1 else "")
    return Div(
        class_="flex min-w-0 flex-col gap-3",
        data_supported_form_layout=str(columns),
    )[
        Div(class_="flex flex-wrap items-center gap-2")[
            Badge(label, tone="brand"),
            Element("h4", [("class", "text-type-section text-heading")])[name],
        ],
        P(class_="text-type-body text-body")[explanation],
        Div(class_="rounded-base border border-default p-4")[
            SettingsFieldLayout(columns)[*_column_fields(f"columns-{columns}")]
        ],
    ]


def _column_fields(prefix: str):
    return [
        _preview_checkbox_field(prefix),
        _preview_standard_field(prefix, kind="destination"),
        _preview_standard_field(prefix, kind="limit"),
    ]


def _supported_form_layouts():
    return Div(class_="flex flex-col gap-6", data_supported_form_layouts="")[
        _supported_form_layout(
            columns=1,
            name="Constrained vertical form",
            explanation="Best scanning order and room for help, errors, and long translated labels.",
        ),
        _supported_form_layout(
            columns=2,
            name="Responsive paired fields",
            explanation="For independent compact settings; collapses to one column on narrow screens.",
        ),
        _supported_form_layout(
            columns=3,
            name="Responsive compact grid",
            explanation="For short uniform controls; collapses through two columns to one as space narrows.",
        ),
    ]


@login_required
def settings_kit_preview(request: HttpRequest) -> HttpResponse:
    """Render every reusable settings-kit state without touching stored settings."""

    sections = [
        SettingsSection(
            "supported-form-layouts",
            "Supported form layouts",
            _supported_form_layouts(),
            "The complete one-, two-, and three-column layouts exposed by SettingsFieldLayout.",
        ),
        SettingsSection(
            "live-settings-fields",
            "Live grouped settings fields",
            _live_fields(request),
            "Successful changes show a toast and stay in client memory until reload.",
        ),
        SettingsSection(
            "setting-source-and-lock-states",
            "Setting source and lock states",
            _source_gallery(),
            "Every origin label plus the composite locked treatment.",
        ),
        SettingsSection(
            "masked-secret-values",
            "Masked secret values",
            Div(class_="grid grid-cols-1 gap-6 lg:grid-cols-2")[
                MaskedSecretField(
                    label="Configured secret",
                    present=True,
                    id="preview-secret-present",
                ),
                MaskedSecretField(
                    label="Missing secret",
                    present=False,
                    id="preview-secret-missing",
                ),
            ],
            "Only presence reaches the component; no real secret is accepted or rendered.",
        ),
        SettingsSection(
            "semantic-badge-tones",
            "Semantic badge tones",
            _badge_gallery(),
            "The shared badge primitive owns all semantic color pairings.",
        ),
        SettingsSection(
            "responsive-navigation-behavior",
            "Responsive navigation behavior",
            Div(class_="flex min-h-64 flex-col gap-3")[
                P(class_="text-type-body text-body")[
                    "Resize the content area: section links move into the Settings sections bottom sheet on narrow widths and return to a sticky rail on wide widths."
                ],
                P(class_="text-type-body text-body")[
                    "The same navigation nodes move between those layouts; the page does not render duplicate mobile and desktop navigation."
                ],
            ],
            "A live target for the bottom-sheet and sticky-rail behavior.",
        ),
    ]
    intro = ContentContainer(class_="mb-6 flex flex-col gap-3")[
        PageHeading(["Settings UI kit preview"]),
        Div(class_="flex flex-wrap gap-2")[
            Badge("DEBUG only", tone="warning"),
            Badge("No persistence", tone="neutral"),
        ],
        P(class_="max-w-3xl text-type-body text-body")[
            "This authenticated developer page exercises the complete issue #384 UI kit. Preview saves never write to the database and reset when the page reloads."
        ],
    ]
    return render_page(
        request,
        Div(class_="flex flex-col")[intro, SettingsScaffold(sections)],
        title="Settings UI kit preview",
        is_settings_page=True,
    )


@login_required
@require_http_methods(["PATCH"])
def settings_kit_preview_patch(request: HttpRequest, key: str) -> HttpResponse:
    """Exercise live-save success/error behavior without persisting anything."""

    if key not in _PREVIEW_KEYS:
        return JsonResponse({"detail": "Unknown preview setting."}, status=404)
    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError, UnicodeDecodeError:
        return JsonResponse({"detail": "Expected a JSON object."}, status=400)
    if not isinstance(payload, dict) or "value" not in payload:
        return JsonResponse({"detail": "Expected a value field."}, status=400)
    if payload["value"] == "reject":
        return JsonResponse(
            {"detail": "Rejected intentionally by the preview."},
            status=422,
        )
    messages.success(request, f"{_PREVIEW_KEYS[key]} saved (preview only)")
    return HttpResponse(status=204)


__all__ = ["settings_kit_preview", "settings_kit_preview_patch"]
