"""Authenticated personal settings page shared with later settings stages."""

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django.middleware.csrf import get_token
from django.urls import reverse

from common.components import (
    ControlButton,
    Div,
    FormFieldPresentation,
    LiveSettingFields,
    Node,
    ReadonlySettingField,
    SectionedPage,
    SectionedPageHeader,
    SectionedPageSection,
    SettingsFieldLayout,
    ThemeSetting,
)
from common.layout import render_page
from games.settings_forms import SiteSettingsForm, UserSettingsForm, settings_page_data
from timetracker.settings_commands import SettingNamespace
from timetracker.settings_export import export_site_settings_ini
from timetracker.settings_registry import SETTINGS_REGISTRY, SettingScope
from timetracker.settings_resolver import resolve_with_origin


@login_required
def user_settings(request: HttpRequest) -> HttpResponse:
    page = settings_page_data(
        UserSettingsForm,
        user=request.user,
        presentations={"theme": FormFieldPresentation(decorate_control=ThemeSetting)},
    )
    patch_url = reverse(
        "api-1.0.0:update_user_setting",
        kwargs={"key": "__key__"},
    )
    sections = [
        SectionedPageSection(
            "preferences",
            "Preferences",
            LiveSettingFields(
                page.form,
                states=page.states,
                patch_url_template=patch_url,
                csrf=get_token(request),
                namespace=SettingNamespace.USER,
                presentations=page.presentations,
            ),
            "Account, presentation, and purchase-entry preferences.",
        )
    ]
    content = SectionedPage(
        "Settings",
        sections,
        navigation_label="Settings sections",
        jump_label="Jump to a section",
    )
    return render_page(request, content, title="Settings", is_settings_page=True)


def _infra_fields() -> list[Node]:
    """Build one ReadonlySettingField per INFRA setting, in registry order."""
    rows: list[Node] = []
    for definition in SETTINGS_REGISTRY.values():
        if definition.scope is not SettingScope.INFRA:
            continue
        resolved = resolve_with_origin(definition.key)
        rows.append(
            ReadonlySettingField(
                name=definition.env_name or definition.key,
                value="" if definition.secret else str(resolved.value),
                source=str(resolved.source),
                namespace=SettingNamespace.SITE,
                setting_key=definition.key,
                locked=resolved.locked,
                help_text=definition.help_text,
                note=definition.note,
                secret_present=bool(resolved.value) if definition.secret else None,
            )
        )
    return rows


@login_required
def admin_settings(request: HttpRequest) -> HttpResponse:
    if not request.user.is_superuser:
        content = Div(class_="flex flex-col")[
            SectionedPageHeader(
                "Admin settings",
                description="Superuser access is required to manage site defaults.",
            )
        ]
        return render_page(
            request,
            content,
            title="Admin settings",
            is_settings_page=True,
            status=403,
        )

    page = settings_page_data(SiteSettingsForm)
    patch_url = reverse(
        "api-1.0.0:update_site_setting",
        kwargs={"key": "__key__"},
    )
    sections = [
        SectionedPageSection(
            "site-defaults",
            "Site defaults",
            LiveSettingFields(
                page.form,
                states=page.states,
                patch_url_template=patch_url,
                csrf=get_token(request),
                namespace=SettingNamespace.SITE,
                presentations=page.presentations,
            ),
            "Defaults inherited by users who have not saved personal overrides.",
        ),
        SectionedPageSection(
            "infrastructure",
            "Infrastructure",
            SettingsFieldLayout(1)[*_infra_fields()],
            (
                "Deployment and security configuration, resolved read-only. "
                "Change via env / settings.ini and restart."
            ),
        ),
    ]
    content = SectionedPage(
        "Admin settings",
        sections,
        description="Defaults inherited by users who have not saved personal overrides.",
        actions=ControlButton(
            href=reverse("games:export_admin_settings_ini"),
            color="gray",
        )["Download settings.ini"],
        navigation_label="Settings sections",
        jump_label="Jump to a section",
    )
    return render_page(
        request,
        content,
        title="Admin settings",
        is_settings_page=True,
    )


@login_required
def export_admin_settings_ini(request: HttpRequest) -> HttpResponse:
    # A bare 403 (not the rendered admin_settings() 403 page) is deliberate: this
    # is a download endpoint reached only via a button superusers already see —
    # a direct non-superuser hit gets a plain denial, not a styled page.
    if not request.user.is_superuser:
        return HttpResponseForbidden("Superuser access is required.")
    response = HttpResponse(
        export_site_settings_ini(), content_type="text/plain; charset=utf-8"
    )
    response["Content-Disposition"] = 'attachment; filename="settings.ini"'
    return response


__all__ = [
    "admin_settings",
    "export_admin_settings_ini",
    "user_settings",
]
