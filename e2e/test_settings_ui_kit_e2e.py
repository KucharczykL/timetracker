"""Isolated mobile/desktop and live-save coverage for the Stage 3 settings kit.

The synthetic URLconf deliberately does not add `/settings` or
`/admin-settings`; page consumption belongs to later epic stages.
"""

import json

from django import forms
from django.contrib import messages
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.middleware.csrf import get_token
from django.test import override_settings
from django.urls import path
from django.views.decorators.http import require_http_methods
from playwright.sync_api import Page, expect

from common.components import (
    Div,
    FormFieldGroup,
    LiveSettingFields,
    MaskedSecretField,
    PageHeading,
    SettingFieldState,
    SettingsScaffold,
    SettingsSection,
)
from common.layout import render_page
from games.forms import PrimitiveWidgetsMixin
from timetracker.urls import urlpatterns as base_urlpatterns


class KitHarnessForm(PrimitiveWidgetsMixin, forms.Form):
    enabled = forms.BooleanField(required=False, initial=True)
    destination = forms.ChoiceField(
        choices=[("library", "Library"), ("stats", "Statistics")],
        initial="library",
    )
    limit = forms.IntegerField(required=False, initial=10, min_value=1)
    display_name = forms.CharField(required=False, initial="Before")
    pinned_url = forms.CharField(required=False, initial="https://example.test")


def settings_kit_view(request: HttpRequest) -> HttpResponse:
    form = KitHarnessForm()
    groups = [
        FormFieldGroup(
            "Preferences",
            ("enabled", "destination", "limit", "display_name"),
            "Every ordinary widget stays on the shared Django form path.",
            "preference-fields",
        ),
        FormFieldGroup("Managed", ("pinned_url",)),
    ]
    states = {
        "enabled": SettingFieldState("ENABLED", "user"),
        "destination": SettingFieldState("DESTINATION", "database"),
        "limit": SettingFieldState("LIMIT", "default"),
        "display_name": SettingFieldState("DISPLAY_NAME", "user"),
        "pinned_url": SettingFieldState(
            "APP_URL",
            "env",
            locked=True,
            reason="Change APP_URL in the environment and restart.",
        ),
    }
    fields = LiveSettingFields(
        form,
        states=states,
        patch_url_template="/settings-kit-patch/__key__/",
        csrf=get_token(request),
        groups=groups,
    )
    sections = [
        SettingsSection(
            "general-preferences",
            "General preferences",
            fields,
            "Common behavior and defaults.",
        ),
        SettingsSection(
            "appearance-and-formatting",
            "Appearance and formatting",
            Div(class_="h-96")["Appearance controls arrive in a later stage."],
        ),
        SettingsSection(
            "notifications-and-reminders",
            "Notifications and reminders",
            Div(class_="h-96")["Notification controls arrive in a later stage."],
        ),
        SettingsSection(
            "privacy-and-data",
            "Privacy and data",
            Div(class_="h-96")["Privacy controls arrive in a later stage."],
        ),
        SettingsSection(
            "infrastructure",
            "Infrastructure",
            Div(class_="flex flex-col gap-4 h-96")[
                MaskedSecretField(label="Secret key", present=True),
                Div()["Infrastructure inspector content."],
            ],
        ),
    ]
    return render_page(
        request,
        Div(class_="flex flex-col gap-4")[
            PageHeading(["Settings kit test"]), SettingsScaffold(sections)
        ],
        title="Settings kit test",
    )


@require_http_methods(["PATCH"])
def settings_kit_patch(request: HttpRequest, key: str) -> HttpResponse:
    payload = json.loads(request.body)
    if payload.get("value") == "reject":
        return JsonResponse({"detail": "Rejected for the test."}, status=422)
    messages.success(request, f"{key} saved")
    return HttpResponse(status=204)


urlpatterns = [
    *base_urlpatterns,
    path("settings-kit-test/", settings_kit_view),
    path("settings-kit-patch/<str:key>/", settings_kit_patch),
]


@override_settings(ROOT_URLCONF="e2e.test_settings_ui_kit_e2e")
def test_mobile_scaffold_groups_locked_and_masked_fields(live_server, page: Page):
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{live_server.url}/settings-kit-test/")

    scaffold = page.locator("[data-settings-scaffold]")
    sections = scaffold.locator("[data-settings-section]")
    expect(sections).to_have_count(5)
    first_box = sections.nth(0).bounding_box()
    second_box = sections.nth(1).bounding_box()
    assert first_box and second_box
    assert second_box["y"] > first_box["y"] + first_box["height"]
    assert abs(second_box["x"] - first_box["x"]) < 2

    # The title/description are one tight header group; nested form content is
    # separated more strongly so the description cannot look attached to it.
    first_section = sections.nth(0)
    expect(first_section).to_have_css("row-gap", "24px")
    expect(first_section.locator("[data-settings-section-header]")).to_have_css(
        "row-gap", "8px"
    )
    section_heading = first_section.locator("[data-settings-section-header] h2")
    group_heading = first_section.locator("fieldset legend").first
    expect(section_heading).to_have_css("font-size", "20px")
    expect(section_heading).to_have_css("font-weight", "700")
    expect(group_heading).to_have_css("font-size", "18px")
    expect(group_heading).to_have_css("font-weight", "600")

    # The long chip set cannot fit at 390px, so rightmost *same nodes* move to
    # the More dropdown instead of being cloned or wrapped into another nav.
    overflow = page.locator("[data-section-nav-overflow]")
    expect(overflow).to_be_visible()
    expect(
        page.locator("[data-section-nav-primary] [data-section-nav-item]")
    ).not_to_have_count(5)
    expect(page.locator("[data-menu] [data-section-nav-item]")).not_to_have_count(0)

    # Grouped FormFields owns all four native widget types.
    expect(page.locator("fieldset")).to_have_count(2)
    expect(page.get_by_text("Preferences", exact=True)).to_be_visible()
    expect(page.locator('input[name="enabled"][type="checkbox"]')).to_be_attached()
    expect(page.locator('select[name="destination"]')).to_be_attached()
    expect(page.locator('input[name="limit"][type="number"]')).to_be_attached()
    expect(page.locator('input[name="display_name"][type="text"]')).to_be_attached()

    locked = page.locator('input[name="pinned_url"]')
    expect(locked).to_be_disabled()
    locked_badge = page.locator('[data-setting-origin="env"][data-setting-locked]')
    expect(locked_badge).to_be_visible()
    expect(locked_badge).to_contain_text("Environment")
    expect(locked_badge.locator("svg")).to_be_visible()
    locked_badge.hover()
    locked_tooltip = page.locator("#id_pinned_url_setting_source_tooltip")
    expect(locked_tooltip).to_be_visible()
    expect(locked_tooltip).to_contain_text(
        "Source: Loaded from an environment variable."
    )
    expect(locked_tooltip).to_contain_text(
        "Locked: Change APP_URL in the environment and restart."
    )
    page.mouse.move(0, 0)
    expect(locked_tooltip).to_be_hidden()

    unlocked_badge = page.locator('[data-setting-origin="database"]')
    unlocked_badge.hover()
    unlocked_tooltip = page.locator("#id_destination_setting_source_tooltip")
    expect(unlocked_tooltip).to_be_visible()
    expect(unlocked_tooltip).to_contain_text(
        "Source: Saved in the application database as the current site-wide value."
    )
    expect(unlocked_tooltip).not_to_contain_text("Locked:")
    expect(
        page.locator("[data-setting-metadata]").get_by_text(
            "Change APP_URL in the environment and restart."
        )
    ).to_be_visible()

    masked = page.locator("[data-masked-secret] input")
    expect(masked).to_have_attribute("type", "password")
    expect(masked).to_have_attribute("readonly", "readonly")
    assert masked.input_value() == "••••••••"
    assert "super-secret-value" not in page.content()


@override_settings(ROOT_URLCONF="e2e.test_settings_ui_kit_e2e")
def test_desktop_scaffold_promotes_same_nav_to_sticky_rail(live_server, page: Page):
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(f"{live_server.url}/settings-kit-test/")

    nav_host = page.locator("settings-section-nav")
    nav = nav_host.locator("nav")
    first_section = page.locator("[data-settings-section]").first
    expect(
        page.locator("[data-section-nav-primary] [data-section-nav-item]")
    ).to_have_count(5)
    expect(page.locator("[data-section-nav-overflow]")).to_be_hidden()
    expect(nav).to_have_css("position", "sticky")
    nav_box = nav_host.bounding_box()
    section_box = first_section.bounding_box()
    assert nav_box and section_box
    assert nav_box["x"] < section_box["x"]
    assert abs(nav_box["y"] - section_box["y"]) < 2

    page.evaluate("window.scrollTo(0, 1000)")
    page.wait_for_timeout(50)
    stuck_box = nav.bounding_box()
    assert stuck_box and stuck_box["y"] <= 18


@override_settings(ROOT_URLCONF="e2e.test_settings_ui_kit_e2e")
def test_live_save_toasts_and_reverts_on_error(live_server, page: Page):
    page.goto(f"{live_server.url}/settings-kit-test/")
    control = page.locator('input[name="display_name"]')

    control.fill("Saved name")
    with page.expect_response(
        lambda response: (
            "/settings-kit-patch/DISPLAY_NAME/" in response.url
            and response.request.method == "PATCH"
        )
    ) as saved_response:
        control.press("Tab")
    assert saved_response.value.status == 204
    expect(page.get_by_text("DISPLAY_NAME saved", exact=True)).to_be_visible()
    expect(control).to_have_value("Saved name")

    control.fill("reject")
    with page.expect_response(
        lambda response: (
            "/settings-kit-patch/DISPLAY_NAME/" in response.url
            and response.request.method == "PATCH"
        )
    ) as rejected_response:
        control.press("Tab")
    assert rejected_response.value.status == 422
    expect(control).to_have_value("Saved name")
    expect(page.get_by_text("Couldn't save your change")).to_be_visible()


@override_settings(ROOT_URLCONF="e2e.test_settings_ui_kit_e2e")
def test_each_native_widget_patches_with_its_json_type(live_server, page: Page):
    page.goto(f"{live_server.url}/settings-kit-test/")
    requests = []
    page.on(
        "request",
        lambda request: (
            requests.append(request) if "/settings-kit-patch/" in request.url else None
        ),
    )

    page.locator('input[name="enabled"]').click()
    page.locator('select[name="destination"]').select_option("stats")
    number = page.locator('input[name="limit"]')
    number.fill("25")
    number.press("Tab")
    text = page.locator('input[name="display_name"]')
    text.fill("Player")
    text.press("Tab")

    page.wait_for_function(
        "() => performance.getEntriesByType('resource')"
        ".filter(entry => entry.name.includes('/settings-kit-patch/')).length >= 4"
    )
    payloads = {
        request.url.rsplit("/", 2)[-2]: request.post_data_json for request in requests
    }
    assert payloads == {
        "ENABLED": {"value": False},
        "DESTINATION": {"value": "stats"},
        "LIMIT": {"value": 25},
        "DISPLAY_NAME": {"value": "Player"},
    }
