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
    ContentContainer,
    Div,
    Element,
    FormFieldGroup,
    LiveSettingFields,
    MaskedSecretField,
    PageHeading,
    SettingFieldState,
    SettingSourceBadge,
    SettingsScaffold,
    SettingsSection,
)
from common.components.primitives import P
from common.layout import render_page
from games.forms import PrimitiveWidgetsMixin

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
            ),
        ],
    ]


def _badge_gallery():
    return Div(
        class_="flex flex-wrap items-center gap-3",
        data_badge_tone_gallery="",
    )[*[Badge(tone.title(), tone=tone) for tone in _BADGE_TONES]]


def _hierarchy_sample(
    *,
    option: str,
    name: str,
    explanation: str,
    outer_heading_class: str,
    sample_class: str,
    nested_class: str = "",
):
    return Div(
        class_="flex min-w-0 flex-col gap-3",
        data_section_hierarchy_variant=option,
    )[
        Div(class_="flex flex-wrap items-center gap-2")[
            Badge(option, tone="brand"),
            Element("h3", [("class", "text-type-subheading text-heading")])[name],
        ],
        P(class_="text-type-body text-body")[explanation],
        Div(
            class_=f"rounded-base border border-default p-4 {sample_class}",
        )[
            Div(class_="flex flex-col gap-2")[
                Element("h4", [("class", outer_heading_class)])[
                    "Live grouped settings fields"
                ],
                P(class_="text-type-body text-body")[
                    "Successful changes show a toast and stay in client memory until reload."
                ],
            ],
            Div(class_=nested_class)[
                Element("h5", [("class", "text-type-section text-heading")])[
                    "Preferences"
                ],
                P(class_="text-type-body text-body")[
                    "Checkbox, select, number, and text controls use the shared form path."
                ],
            ],
        ],
    ]


def _section_hierarchy_gallery():
    return Div(class_="grid grid-cols-1 gap-6 xl:grid-cols-3")[
        _hierarchy_sample(
            option="Option 1",
            name="Typography + spacing",
            explanation="20px/700 outside, 18px/600 inside, with 8px/24px grouping.",
            outer_heading_class="text-type-subheading text-heading",
            sample_class="flex flex-col gap-6",
            nested_class="flex flex-col gap-3",
        ),
        _hierarchy_sample(
            option="Option 2",
            name="Spacing hierarchy",
            explanation="Matching heading styles, grouped by 8px inside and 24px before content.",
            outer_heading_class="text-type-section text-heading",
            sample_class="flex flex-col gap-6",
            nested_class="flex flex-col gap-3",
        ),
        _hierarchy_sample(
            option="Option 3",
            name="Divider hierarchy",
            explanation="Matching heading styles, separated by a thin but visible structural rule.",
            outer_heading_class="text-type-section text-heading",
            sample_class="flex flex-col gap-4",
            nested_class="flex flex-col gap-3 border-t border-default-strong pt-4",
        ),
    ]


@login_required
def settings_kit_preview(request: HttpRequest) -> HttpResponse:
    """Render every reusable settings-kit state without touching stored settings."""

    sections = [
        SettingsSection(
            "section-hierarchy-comparison",
            "Section hierarchy comparison",
            _section_hierarchy_gallery(),
            "The same content with typography, spacing, and divider treatments isolated for comparison.",
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
                    "Resize the content area: section links collapse into a More menu on narrow widths and become a sticky rail on wide widths."
                ],
                P(class_="text-type-body text-body")[
                    "The same navigation nodes move between those layouts; the page does not render duplicate mobile and desktop navigation."
                ],
            ],
            "A live target for the priority-plus and sticky-rail behavior.",
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
