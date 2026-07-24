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
from playwright.sync_api import Browser, Page, expect

from common.components import (
    Badge,
    BadgeTone,
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
from timetracker.settings_commands import SettingNamespace
from timetracker.urls import urlpatterns as base_urlpatterns

_BADGE_TONES: tuple[BadgeTone, ...] = (
    "brand",
    "neutral",
    "success",
    "warning",
    "danger",
)


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
        namespace=SettingNamespace.USER,
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
            "setting-source-and-lock-states",
            "Setting source and lock states",
            Div(class_="h-96")["Source and lock controls arrive in a later stage."],
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
                Div(
                    data_badge_tone_contract="",
                    class_="flex flex-wrap items-center gap-3",
                )[
                    *[
                        Badge(
                            tone.title(),
                            tone=tone,
                            attributes=[("data-badge-tone", tone)],
                        )
                        for tone in _BADGE_TONES
                    ]
                ],
                Div()["Infrastructure inspector content."],
            ],
        ),
    ]
    return render_page(
        request,
        Div(class_="flex flex-col gap-4")[
            PageHeading(["Settings kit test"]),
            SettingsScaffold(sections),
            # Test-only runway proving the sticky host stops with its scaffold.
            Div(data_settings_after_scaffold="", class_="min-h-screen")[
                "Content after the settings scaffold."
            ],
        ],
        title="Settings kit test",
    )


@require_http_methods(["PATCH"])
def settings_kit_patch(request: HttpRequest, key: str) -> HttpResponse:
    payload = json.loads(request.body)
    if payload.get("value") == "reject":
        return JsonResponse({"detail": "Rejected for the test."}, status=422)
    messages.success(request, f"{key} saved")
    return JsonResponse(
        {
            "key": key,
            "value": payload.get("value"),
            "source": "user",
            "locked": False,
            "namespace": "user",
        }
    )


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
    expect(first_section.locator("[data-form-checkbox-row]")).to_have_css(
        "column-gap", "24px"
    )

    # Enhancement replaces the otherwise-visible inline fallback with one
    # self-explanatory, full-width sheet trigger. The entire same-DOM list is
    # waiting inside the closed dialog; it never gains ARIA-menu semantics.
    nav_host = page.locator("settings-section-nav")
    trigger = nav_host.locator("[data-section-nav-trigger]")
    rail = nav_host.locator("[data-section-nav-rail]")
    sheet = nav_host.locator("[data-section-nav-sheet]")
    expect(trigger).to_be_visible()
    expect(trigger).to_contain_text("Settings sections")
    expect(trigger).to_contain_text("Jump to a section")
    expect(rail).to_be_hidden()
    expect(sheet).to_be_visible()
    expect(sheet.locator("[data-section-nav-item]")).to_have_count(5)
    expect(sheet.locator("[role='menu'], [role='menuitem']")).to_have_count(0)
    trigger_box = trigger.bounding_box()
    host_box = nav_host.bounding_box()
    assert trigger_box and host_box
    assert abs(trigger_box["width"] - host_box["width"]) < 2

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
    expect(locked_tooltip.locator("dt").nth(0)).to_have_text("Source")
    expect(locked_tooltip.locator("dd").nth(0)).to_have_text(
        "Loaded from an environment variable."
    )
    expect(locked_tooltip.locator("dt").nth(1)).to_have_text("Locked")
    expect(locked_tooltip.locator("dd").nth(1)).to_have_text(
        "Change APP_URL in the environment and restart."
    )
    page.mouse.move(0, 0)
    expect(locked_tooltip).to_be_hidden()

    unlocked_badge = page.locator('[data-setting-origin="database"]')
    unlocked_badge.hover()
    unlocked_tooltip = page.locator("#id_destination_setting_source_tooltip")
    expect(unlocked_tooltip).to_be_visible()
    expect(unlocked_tooltip.locator("dt").nth(0)).to_have_text("Source")
    expect(unlocked_tooltip.locator("dd").nth(0)).to_have_text(
        "Saved in the application database as the current site-wide value."
    )
    expect(unlocked_tooltip.locator("dt").nth(1)).to_have_text("Status")
    expect(unlocked_tooltip.locator("dd").nth(1)).to_have_text(
        "Non-default source (default source: “Default”)"
    )
    expect(unlocked_tooltip.locator("dt")).to_have_count(2)

    # Neutral badges retain a visible chip silhouette against settings surfaces
    # in both themes; they must not collapse into plain inline text.
    section_surface = page.locator("#general-preferences")
    for theme in ("light", "dark"):
        page.locator("html").evaluate(
            "(element, dark) => element.classList.toggle('dark', dark)",
            theme == "dark",
        )
        badge_background = unlocked_badge.evaluate(
            "element => getComputedStyle(element).backgroundColor"
        )
        surface_background = section_surface.evaluate(
            "element => getComputedStyle(element).backgroundColor"
        )
        assert badge_background != surface_background
        expect(unlocked_badge).to_have_css("border-top-width", "0px")
    page.locator("html").evaluate("element => element.classList.remove('dark')")

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
def test_badge_tones_share_one_structural_contract(live_server, page: Page):
    page.goto(f"{live_server.url}/settings-kit-test/")
    badges = page.locator("[data-badge-tone-contract] [data-badge-tone]")
    expect(badges).to_have_count(5)

    for dark in (False, True):
        page.locator("html").evaluate(
            "(element, enabled) => element.classList.toggle('dark', enabled)",
            dark,
        )
        structures = badges.evaluate_all(
            """elements => elements.map(element => {
                const style = getComputedStyle(element);
                return {
                    borderWidth: style.borderWidth,
                    borderRadius: style.borderRadius,
                    paddingBlock: style.paddingBlock,
                    paddingInline: style.paddingInline,
                    fontFamily: style.fontFamily,
                    fontSize: style.fontSize,
                    fontWeight: style.fontWeight,
                    lineHeight: style.lineHeight,
                };
            })"""
        )
        assert structures == [structures[0]] * len(structures)
        assert structures[0]["borderWidth"] == "0px"

    page.locator("html").evaluate("element => element.classList.remove('dark')")


@override_settings(ROOT_URLCONF="e2e.test_settings_ui_kit_e2e")
def test_desktop_scaffold_promotes_same_nav_to_sticky_rail(live_server, page: Page):
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(f"{live_server.url}/settings-kit-test/")

    nav_host = page.locator("settings-section-nav")
    nav = nav_host.locator("[data-section-nav-rail]")
    scaffold = page.locator("[data-settings-scaffold]")
    first_section = page.locator("[data-settings-section]").first
    expect(nav.locator("[data-section-nav-item]")).to_have_count(5)
    expect(nav_host.locator("[data-section-nav-sheet]")).to_be_hidden()
    expect(nav_host).to_have_css("position", "sticky")
    expect(nav_host).to_have_css("top", "16px")
    expect(nav).to_have_css("position", "static")
    expect(nav).to_have_css("overflow-y", "auto")

    # The public dropdown API cannot reopen the hidden mobile sheet after the
    # navigation list has moved into its desktop rail.
    dialog = nav_host.locator("dialog[data-bottom-sheet]")
    nav_host.locator("[data-section-nav-sheet] drop-down").evaluate(
        "element => element.open()"
    )
    expect(dialog).not_to_have_attribute("open", "")
    assert page.evaluate("document.documentElement.style.overflow") == ""
    assert page.evaluate("document.body.style.position") == ""

    primary_links = nav.locator("[data-section-nav-list] a[href^='#']")
    overflowing_labels = primary_links.evaluate_all(
        """elements => elements
            .filter(element => element.scrollWidth > element.clientWidth)
            .map(element => element.textContent?.trim() || "<unnamed>")"""
    )
    assert overflowing_labels == [], (
        f"Section labels exceed the 14rem rail: {overflowing_labels}"
    )
    assert nav.evaluate("element => element.scrollWidth <= element.clientWidth")

    first_link = primary_links.first
    first_link.focus()
    assert "inset" in first_link.evaluate(
        "element => getComputedStyle(element).boxShadow"
    )

    nav_box = nav_host.bounding_box()
    section_box = first_section.bounding_box()
    scaffold_box = scaffold.bounding_box()
    assert nav_box and section_box and scaffold_box
    assert nav_box["x"] < section_box["x"]
    assert abs(nav_box["y"] - section_box["y"]) < 2
    assert nav_box["y"] > 66
    assert scaffold_box["height"] > nav_box["height"] + 100
    single_column = first_section.locator('[data-settings-field-layout="1"]')
    expect(single_column).to_have_css("max-width", "576px")
    single_column_box = single_column.bounding_box()
    assert single_column_box
    assert single_column_box["width"] < section_box["width"] - 32

    target = nav_box["y"] + 100
    max_scroll = page.evaluate(
        "document.documentElement.scrollHeight - window.innerHeight"
    )
    assert target <= max_scroll
    page.evaluate("target => window.scrollTo(0, target)", target)
    page.wait_for_function("target => window.scrollY >= target - 1", arg=target)
    stuck_box = nav_host.bounding_box()
    assert stuck_box and 14 <= stuck_box["y"] <= 18

    after_scaffold = page.locator("[data-settings-after-scaffold]")
    after_document_y = after_scaffold.evaluate(
        "element => element.getBoundingClientRect().top + window.scrollY"
    )
    max_scroll = page.evaluate(
        "document.documentElement.scrollHeight - window.innerHeight"
    )
    assert after_document_y <= max_scroll
    page.evaluate("target => window.scrollTo(0, target)", after_document_y)
    page.wait_for_function(
        "target => window.scrollY >= target - 1",
        arg=after_document_y,
    )
    stopped_box = nav_host.bounding_box()
    after_box = after_scaffold.bounding_box()
    assert stopped_box and after_box
    assert stopped_box["y"] + stopped_box["height"] <= after_box["y"] + 1


@override_settings(ROOT_URLCONF="e2e.test_settings_ui_kit_e2e")
def test_desktop_section_nav_scrolls_in_short_viewport(live_server, page: Page):
    page.set_viewport_size({"width": 1280, "height": 240})
    page.goto(f"{live_server.url}/settings-kit-test/")

    nav_host = page.locator("settings-section-nav")
    nav = nav_host.locator("[data-section-nav-rail]")
    expect(nav_host).to_have_css("position", "sticky")
    expect(nav).to_have_css("overflow-y", "auto")
    assert nav.evaluate("element => element.scrollHeight > element.clientHeight")

    window_y = page.evaluate("window.scrollY")
    nav.evaluate("element => { element.scrollTop = element.scrollHeight; }")
    assert nav.evaluate("element => element.scrollTop") > 0
    assert page.evaluate("window.scrollY") == window_y


@override_settings(ROOT_URLCONF="e2e.test_settings_ui_kit_e2e")
def test_mobile_section_sheet_navigation_and_dismissal(live_server, page: Page):
    page.set_viewport_size({"width": 390, "height": 600})
    page.goto(f"{live_server.url}/settings-kit-test/")

    nav_host = page.locator("settings-section-nav")
    trigger = nav_host.locator("[data-section-nav-trigger]")
    dialog = nav_host.locator("dialog[data-bottom-sheet]")
    panel = dialog.locator("[data-sheet-panel]")
    close_button = dialog.locator("[data-sheet-dismiss]")
    links = dialog.locator("[data-section-nav-item] a")

    # The compact control travels as a sticky grid item on a reachable scroll.
    page.evaluate("window.scrollTo(0, 240)")
    page.wait_for_function("window.scrollY >= 239")
    sticky_box = nav_host.bounding_box()
    assert sticky_box and 14 <= sticky_box["y"] <= 18

    trigger.click()
    expect(dialog).to_have_attribute("open", "")
    expect(trigger).to_have_attribute("aria-expanded", "true")
    assert dialog.evaluate("element => element.matches(':modal')")
    expect(links.first).to_be_focused()

    dialog_box = dialog.bounding_box()
    panel_box = panel.bounding_box()
    assert dialog_box and panel_box
    assert abs(panel_box["y"] + panel_box["height"] - dialog_box["height"]) < 2
    assert panel_box["height"] <= min(600 * 0.8, 512) + 2
    expect(page.locator("html")).to_have_css("overflow", "hidden")
    expect(page.locator("body")).to_have_css("position", "fixed")

    # Native modality keeps sequential and scripted focus out of the page.
    for _ in range(links.count() + 3):
        page.keyboard.press("Tab")
        assert dialog.evaluate("element => element.contains(document.activeElement)")
    page.keyboard.press("Shift+Tab")
    assert dialog.evaluate("element => element.contains(document.activeElement)")
    assert not trigger.evaluate(
        "element => { element.focus(); return document.activeElement === element; }"
    )

    page.keyboard.press("Escape")
    expect(dialog).not_to_have_attribute("open", "")
    expect(trigger).to_have_attribute("aria-expanded", "false")
    expect(trigger).to_be_focused()
    expect(page.locator("html")).not_to_have_css("overflow", "hidden")
    expect(page.locator("body")).not_to_have_css("position", "fixed")

    # The explicit close action follows the same cleanup path.
    trigger.click()
    close_button.click()
    expect(dialog).not_to_have_attribute("open", "")
    expect(trigger).to_be_focused()

    # A gesture beginning in the panel is not a backdrop dismissal, even if it
    # ends over the transparent dialog hit area.
    trigger.click()
    panel_box = panel.bounding_box()
    assert panel_box
    page.mouse.move(panel_box["x"] + 20, panel_box["y"] + 20)
    page.mouse.down()
    page.mouse.move(10, 10)
    page.mouse.up()
    expect(dialog).to_have_attribute("open", "")

    # The reverse drag is safe too: starting on the backdrop is insufficient
    # when the same pointer is released over the visible panel.
    page.mouse.move(10, 10)
    page.mouse.down()
    page.mouse.move(panel_box["x"] + 20, panel_box["y"] + 20)
    page.mouse.up()
    expect(dialog).to_have_attribute("open", "")

    # A gesture beginning and ending on the backdrop does dismiss.
    page.mouse.click(10, 10)
    expect(dialog).not_to_have_attribute("open", "")

    # Section navigation closes first, then scrolls and moves accessibility
    # focus to the destination heading below the sticky control.
    trigger.click()
    links.filter(has_text="Privacy and data").click()
    expect(dialog).not_to_have_attribute("open", "")
    expect(page).to_have_url(f"{live_server.url}/settings-kit-test/#privacy-and-data")
    destination = page.locator("#privacy-and-data")
    destination_heading = destination.locator("[data-settings-section-heading]")
    expect(destination_heading).to_be_focused()
    destination_box = destination.bounding_box()
    trigger_box = trigger.bounding_box()
    assert destination_box and trigger_box
    assert destination_box["y"] >= trigger_box["y"] + trigger_box["height"]


@override_settings(ROOT_URLCONF="e2e.test_settings_ui_kit_e2e")
def test_mobile_sheet_scrolls_in_a_short_viewport(live_server, page: Page):
    page.set_viewport_size({"width": 390, "height": 240})
    page.goto(f"{live_server.url}/settings-kit-test/")

    page.locator("[data-section-nav-trigger]").click()
    body = page.locator("[data-sheet-body]")
    assert body.evaluate("element => element.scrollHeight > element.clientHeight")
    body.evaluate("element => { element.scrollTop = element.scrollHeight; }")
    assert body.evaluate("element => element.scrollTop") > 0
    expect(page.locator("dialog[data-bottom-sheet]")).to_have_attribute("open", "")


@override_settings(ROOT_URLCONF="e2e.test_settings_ui_kit_e2e")
def test_open_mobile_sheet_resizes_to_the_same_desktop_rail(live_server, page: Page):
    page.set_viewport_size({"width": 390, "height": 600})
    page.goto(f"{live_server.url}/settings-kit-test/")
    page.evaluate("window.scrollTo(0, 240)")
    page.wait_for_function("window.scrollY >= 239")

    styles_before = page.evaluate(
        """() => ({
            htmlOverflow: document.documentElement.style.overflow,
            htmlOverscroll: document.documentElement.style.overscrollBehavior,
            bodyPosition: document.body.style.position,
            bodyTop: document.body.style.top,
            bodyWidth: document.body.style.width,
            bodyOverflow: document.body.style.overflow,
            bodyPaddingRight: document.body.style.paddingRight,
            scrollX: window.scrollX,
            scrollY: window.scrollY,
        })"""
    )
    page.evaluate(
        "window.__settingsSectionLinks = "
        "Array.from(document.querySelectorAll('[data-section-nav-item] a'))"
    )
    page.locator("[data-section-nav-trigger]").click()
    expect(page.locator("dialog[data-bottom-sheet]")).to_have_attribute("open", "")

    page.set_viewport_size({"width": 1280, "height": 800})
    dialog = page.locator("dialog[data-bottom-sheet]")
    rail = page.locator("[data-section-nav-rail]")
    expect(dialog).not_to_have_attribute("open", "")
    expect(rail).to_be_visible()
    expect(page.locator("[data-section-nav-sheet]")).to_be_hidden()
    assert page.evaluate(
        """() => {
            const current = Array.from(
                document.querySelectorAll('[data-section-nav-item] a')
            );
            return current.length === window.__settingsSectionLinks.length &&
                current.every((link, index) =>
                    link === window.__settingsSectionLinks[index]
                );
        }"""
    )
    styles_after = page.evaluate(
        """() => ({
            htmlOverflow: document.documentElement.style.overflow,
            htmlOverscroll: document.documentElement.style.overscrollBehavior,
            bodyPosition: document.body.style.position,
            bodyTop: document.body.style.top,
            bodyWidth: document.body.style.width,
            bodyOverflow: document.body.style.overflow,
            bodyPaddingRight: document.body.style.paddingRight,
            scrollX: window.scrollX,
            scrollY: window.scrollY,
        })"""
    )
    assert styles_after == styles_before


@override_settings(ROOT_URLCONF="e2e.test_settings_ui_kit_e2e")
def test_section_links_remain_usable_without_javascript(live_server, browser: Browser):
    context = browser.new_context(
        java_script_enabled=False,
        viewport={"width": 390, "height": 600},
    )
    try:
        page = context.new_page()
        page.goto(f"{live_server.url}/settings-kit-test/")

        rail = page.locator("[data-section-nav-rail]")
        links = rail.locator("[data-section-nav-item] a")
        expect(rail).to_be_visible()
        expect(links).to_have_count(5)
        expect(page.locator("[data-section-nav-sheet]")).to_be_hidden()
        links.filter(has_text="Infrastructure").click()
        expect(page).to_have_url(f"{live_server.url}/settings-kit-test/#infrastructure")
    finally:
        context.close()


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
    assert saved_response.value.status == 200
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
