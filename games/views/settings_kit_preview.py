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
    SettingsScaffold,
    SettingsSection,
)
from common.components.primitives import P
from common.layout import render_page
from games.forms import INPUT_CLASS, SELECT_CLASS, PrimitiveWidgetsMixin

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


def _preview_label_line(
    *,
    field_id: str,
    label: str,
    source: str,
    tooltip_id: str,
):
    return Div(class_="flex min-w-0 flex-wrap items-center gap-2")[
        Label(for_=field_id, class_="text-type-label text-heading")[label],
        SettingSourceBadge(source, id=tooltip_id),
    ]


def _preview_checkbox_field(
    prefix: str,
    *,
    placement: str = "trailing",
    gap_class: str = "gap-3",
):
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
    if placement == "leading":
        return Div(
            class_="grid grid-cols-[auto_minmax(0,1fr)] items-start gap-x-3",
            data_preview_checkbox_field="",
        )[
            Div(class_="pt-1")[checkbox],
            Div(class_="flex min-w-0 flex-col gap-2")[label_line, help_text],
        ]
    return Div(class_="flex min-w-0 flex-col gap-2", data_preview_checkbox_field="")[
        Div(class_=f"flex items-center justify-between {gap_class}")[
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


def _layout_option(*, option: str, name: str, explanation: str, content, hook: str):
    return Div(
        class_="flex min-w-0 flex-col gap-3",
        **{hook: option},
    )[
        Div(class_="flex flex-wrap items-center gap-2")[
            Badge(option, tone="brand"),
            Element("h4", [("class", "text-type-section text-heading")])[name],
        ],
        P(class_="text-type-body text-body")[explanation],
        Div(class_="rounded-base border border-default p-4")[content],
    ]


def _column_fields(prefix: str):
    return [
        _preview_checkbox_field(prefix, gap_class="gap-6"),
        _preview_standard_field(prefix, kind="destination"),
        _preview_standard_field(prefix, kind="limit"),
    ]


def _checkbox_and_form_layout_gallery():
    return Div(class_="flex flex-col gap-8", data_checkbox_form_layout_gallery="")[
        Div(class_="flex flex-col gap-2")[
            Element("h3", [("class", "text-type-subheading text-heading")])[
                "Checkbox placement"
            ],
            P(class_="text-type-body text-body")[
                "These use identical content; only the relationship between the label and checkbox changes."
            ],
        ],
        Div(class_="flex flex-col gap-6")[
            _layout_option(
                option="Baseline",
                name="Fluid trailing checkbox",
                explanation="The current rule: acceptable when narrow, but the checkbox drifts to the far edge of a wide single column.",
                content=_preview_checkbox_field("checkbox-fluid"),
                hook="data_checkbox_placement_variant",
            ),
            _layout_option(
                option="Option 1",
                name="Constrained trailing checkbox",
                explanation="Keep the familiar right-aligned control inside a readable-width field column, with a 24px minimum gap.",
                content=Div(class_="max-w-xl")[
                    _preview_checkbox_field("checkbox-constrained", gap_class="gap-6")
                ],
                hook="data_checkbox_placement_variant",
            ),
            _layout_option(
                option="Option 2",
                name="Leading checkbox",
                explanation="Put the control immediately before its label; association stays strong at every container width.",
                content=_preview_checkbox_field(
                    "checkbox-leading",
                    placement="leading",
                ),
                hook="data_checkbox_placement_variant",
            ),
        ],
        Div(class_="flex flex-col gap-2")[
            Element("h3", [("class", "text-type-subheading text-heading")])[
                "Form-field column flow"
            ],
            P(class_="text-type-body text-body")[
                "The production renderer is single-column today. The two- and three-column areas elsewhere on this page are component galleries, not form modes."
            ],
        ],
        Div(class_="flex flex-col gap-6")[
            _layout_option(
                option="1 column",
                name="Constrained vertical form",
                explanation="Best scanning order and room for help, errors, and long translated labels.",
                content=Div(class_="flex max-w-xl flex-col gap-4")[
                    *_column_fields("columns-one")
                ],
                hook="data_form_column_variant",
            ),
            _layout_option(
                option="2 columns",
                name="Responsive paired fields",
                explanation="Useful for independent, compact settings; collapses to one column on narrow screens.",
                content=Div(class_="grid grid-cols-1 gap-6 md:grid-cols-2")[
                    *_column_fields("columns-two")
                ],
                hook="data_form_column_variant",
            ),
            _layout_option(
                option="3 columns",
                name="Responsive compact grid",
                explanation="Only suitable for short, uniform controls; labels and metadata run out of room first.",
                content=Div(
                    class_="grid grid-cols-1 gap-6 md:grid-cols-2 xl:grid-cols-3"
                )[*_column_fields("columns-three")],
                hook="data_form_column_variant",
            ),
        ],
    ]


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
            "checkbox-and-form-layout-comparison",
            "Checkbox and form layout comparison",
            _checkbox_and_form_layout_gallery(),
            "Placement and column-flow candidates using real kit controls and source badges.",
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
