"""The form dialog's server half: links, host, layout stamps."""

import json
import re
from html.parser import HTMLParser

from django import forms
from django.contrib import messages
from django.contrib.auth.models import User
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponse
from django.templatetags.static import static
from django.test import Client, RequestFactory, SimpleTestCase, TestCase
from django.urls import reverse
from tracked_games import create_tracked_game

from common.components import (
    BottomSheet,
    ControlButton,
    Div,
    DropdownLinkItem,
    FormDialogHost,
    Media,
    ModalPanelHeader,
    form_dialog_link,
)
from common.components.form_dialog import (
    FORM_DIALOG_ATTRIBUTE,
    FORM_DIALOG_CHROME_VALUES,
    FORM_DIALOG_ID_ATTRIBUTES,
    FORM_DIALOG_ID_LIST_ATTRIBUTES,
    FORM_DIALOG_PARTS,
    PAGE_WIDTH_ATTRIBUTE,
    UNSAVED_WARNING_PARTS,
)
from common.components.modal import MODAL_ATTRIBUTES
from common.components.primitives import (
    FORM_ERRORS_ATTRIBUTE,
    PAGE_WIDTH_CLASSES,
    PAGE_WIDTHS,
    AddForm,
    ConfirmPage,
    FieldErrors,
    PageWidth,
)
from common.components.ts_codegen import render_filter_metadata_module
from common.form_dialog import FORM_DIALOG_HEADER
from common.layout import render_page
from common.notices import ToastPayload
from games.management.commands.gen_element_types import form_dialog_module
from games.views.bulk_pages import confirmation_width

#: What every dialog fetch sends.
DIALOG_HEADERS = {FORM_DIALOG_HEADER: "1", "Accept": "application/json"}


def _opening_tag(html: str, marker: str) -> str:
    position = html.index(marker)
    start = html.rindex("<", 0, position)
    return html[start : html.index(">", position) + 1]


class FormDialogLinkTest(SimpleTestCase):
    def test_header_chrome_is_the_empty_value(self):
        self.assertIn((FORM_DIALOG_ATTRIBUTE, ""), form_dialog_link())

    def test_bare_chrome_opts_out_of_the_header(self):
        self.assertIn((FORM_DIALOG_ATTRIBUTE, "bare"), form_dialog_link("bare"))

    def test_a_menu_link_carries_the_attribute(self):
        html = str(
            DropdownLinkItem("/device/1/edit", "Edit", attributes=form_dialog_link())
        )
        tag = _opening_tag(html, 'href="/device/1/edit"')
        self.assertTrue(tag.startswith("<a"))
        self.assertIn('data-form-dialog=""', tag)
        self.assertIn("aria-busy:cursor-progress", tag)


class FormDialogHostTest(SimpleTestCase):
    def test_the_dialog_lives_only_inside_the_template(self):
        html = str(FormDialogHost())
        self.assertTrue(html.startswith("<form-dialog"))
        for template in re.findall(r"<template.*?</template>", html, re.DOTALL):
            self.assertEqual(template.count("<dialog"), 1)
        outside = re.sub(r"<template.*?</template>", "", html, flags=re.DOTALL)
        self.assertNotIn("<dialog", outside)

    def test_the_template_names_every_part(self):
        html = str(FormDialogHost())
        for part in [*FORM_DIALOG_PARTS.values(), *UNSAVED_WARNING_PARTS.values()]:
            self.assertIn(f"{part}=", html)

    def test_the_dialog_is_named_by_its_title(self):
        html = str(FormDialogHost())
        title_id = re.search(r'aria-labelledby="([^"]+)"', html)
        assert title_id is not None
        self.assertIn(f'id="{title_id.group(1)}"', html)
        self.assertIn('data-modal-dismiss=""', html)

    def test_the_warning_is_an_alertdialog(self):
        html = str(FormDialogHost())
        start = html.index(f"{UNSAVED_WARNING_PARTS['template']}=")
        warning = html[start : html.index("</template>", start)]
        self.assertIn('role="alertdialog"', warning)
        for attribute in ("aria-labelledby", "aria-describedby"):
            reference = re.search(rf'{attribute}="([^"]+)"', warning)
            assert reference is not None
            self.assertIn(f'id="{reference.group(1)}"', warning)
        self.assertIn("Unsaved changes", warning)
        self.assertIn("Your changes are not saved.", warning)

    def test_the_warning_offers_three_acts_in_order(self):
        html = str(FormDialogHost())
        start = html.index(f"{UNSAVED_WARNING_PARTS['template']}=")
        warning = html[start : html.index("</template>", start)]
        buttons = re.findall(r"<button[^>]*>.*?</button>", warning, re.DOTALL)
        self.assertEqual(len(buttons), 3)
        discard, keep, save = buttons
        self.assertIn(f"{UNSAVED_WARNING_PARTS['discard']}=", discard)
        self.assertIn("Discard", discard)
        self.assertIn('data-modal-dismiss=""', keep)
        self.assertIn('data-modal-initial-focus=""', keep)
        self.assertIn("Return to edit", keep)
        self.assertIn(f"{UNSAVED_WARNING_PARTS['save']}=", save)
        self.assertIn("Save", save)
        for button in buttons:
            self.assertIn('type="button"', button)

    def test_the_generated_module_states_every_value(self):
        module = form_dialog_module()
        self.assertIn(f'"{FORM_DIALOG_ATTRIBUTE}"', module)
        for chrome, value in FORM_DIALOG_CHROME_VALUES.items():
            self.assertIn(f'"{value}": "{chrome}"', module)
        for parts in (FORM_DIALOG_PARTS, UNSAVED_WARNING_PARTS):
            for part, attribute in parts.items():
                self.assertIn(f'"{part}": "{attribute}"', module)


class BottomSheetHeaderTest(SimpleTestCase):
    def test_the_sheet_keeps_its_header(self):
        html = str(
            BottomSheet(
                trigger_element=ControlButton()["Sections"].as_element(),
                title="Sections",
                children=[],
                id="sheet",
            )
        )
        self.assertIn('aria-labelledby="sheet-title"', html)
        self.assertIn('id="sheet-title"', html)
        self.assertIn('aria-label="Close dialog"', html)
        self.assertIn("border-b border-default-medium", html)


class FieldErrorsTest(SimpleTestCase):
    def test_a_form_wide_list_is_marked_and_focusable(self):
        html = str(FieldErrors(["Taken"], form_wide=True))
        self.assertIn(f'{FORM_ERRORS_ATTRIBUTE}=""', html)
        self.assertIn('tabindex="-1"', html)

    def test_a_field_list_is_not_marked(self):
        html = str(FieldErrors(["Required"]))
        self.assertNotIn(FORM_ERRORS_ATTRIBUTE, html)
        self.assertNotIn("tabindex", html)


#: A divided header's own classes.
_DIVIDER = str(ModalPanelHeader("T", title_id="t")).split('class="', 1)[1].split('"')[0]


class ModalPanelHeaderTest(SimpleTestCase):
    def test_a_plain_header_has_no_line_and_no_close(self):
        html = str(
            ModalPanelHeader("Title", title_id="t", close_label=None, divided=False)
        )
        self.assertIn('id="t"', html)
        self.assertNotIn(_DIVIDER, html)
        self.assertNotIn("data-modal-dismiss", html)
        self.assertNotIn("None", html)

    def test_the_warning_wears_the_plain_header(self):
        html = str(FormDialogHost())
        start = html.index(f"{UNSAVED_WARNING_PARTS['template']}=")
        warning = html[start : html.index("</template>", start)]
        self.assertNotIn(_DIVIDER, warning)
        self.assertNotIn("Close dialog", warning)


class LayoutStampTest(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_superuser(
            username="stamp", email="stamp@example.com", password="stamp"
        )
        self.client.force_login(self.user)

    def _main_container(self, html: str) -> str:
        return _opening_tag(html, 'id="main-container"')

    def test_a_list_page_is_read_only(self):
        response = self.client.get(reverse("games:list_devices"))
        html = response.content.decode()
        tag = self._main_container(html)
        self.assertIn("data-read-only", tag)
        self.assertIn('tabindex="-1"', tag)
        self.assertIn("<form-dialog", html)
        self.assertIn(FORM_DIALOG_HEADER, response["Vary"])

    def test_a_form_page_is_not_read_only(self):
        html = self.client.get(reverse("games:add_device")).content.decode()
        tag = self._main_container(html)
        self.assertNotIn("data-read-only", tag)
        self.assertIn("<form-dialog", html)


def _dialog_get(client: Client, url: str):
    return client.get(url, headers=DIALOG_HEADERS)


class DialogModeTest(TestCase):
    """A dialog request answers JSON content."""

    def setUp(self) -> None:
        self.user = User.objects.create_superuser(
            username="dialog", email="dialog@example.com", password="dialog"
        )
        self.client.force_login(self.user)

    def test_a_form_page_answers_its_content(self):
        response = _dialog_get(self.client, reverse("games:add_device"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertIn(FORM_DIALOG_HEADER, response["Vary"])
        answer = response.json()
        self.assertEqual(answer["kind"], "page")
        self.assertEqual(answer["title"], "Add New Device")
        self.assertIn("<form", answer["html"])
        self.assertNotIn("<nav", answer["html"])
        self.assertNotIn("<html", answer["html"])
        self.assertNotIn('id="main-container"', answer["html"])
        self.assertEqual(answer["messages"], [])

    def test_modules_hold_the_content_media(self):
        answer = _dialog_get(self.client, reverse("games:add_game")).json()
        modules = answer["modules"]
        self.assertIn(static("js/dist/elements/temporal-field.js"), modules)
        self.assertIn(static("js/dist/elements/field-mirror.js"), modules)
        self.assertNotIn(static("js/dist/library-conversion-status.js"), modules)

    def test_the_answer_carries_the_queue(self):
        request = RequestFactory().get("/", headers=DIALOG_HEADERS)
        request.user = self.user
        SessionMiddleware(lambda request: HttpResponse()).process_request(request)
        MessageMiddleware(lambda request: HttpResponse()).process_request(request)
        messages.error(request, "Refused")
        response = render_page(
            request, Div()["Body"], title="T", width="form", status=409
        )
        self.assertEqual(response.status_code, 409)
        answer = json.loads(response.content)
        self.assertEqual(answer["messages"], [{"message": "Refused", "type": "error"}])

    def test_an_external_script_is_refused(self):
        request = RequestFactory().get("/", headers=DIALOG_HEADERS)
        request.user = self.user
        content = Div()["Body"].with_media(Media(js_external=("vendor.js",)))
        with self.assertRaises(ImproperlyConfigured):
            render_page(request, content, title="T", width="form")


class PageWidthTest(TestCase):
    """A page's width reaches its container and its dialog."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(username="width", password="width")

    def _request(self, headers: dict[str, str] | None = None):
        request = RequestFactory().get("/", headers=headers or {})
        request.user = self.user
        return request

    def test_each_width_caps_the_page_container(self):
        for width in PAGE_WIDTHS:
            with self.subTest(width=width):
                html = render_page(
                    self._request(), Div(id="page-body")["Body"], width=width
                ).content.decode()
                before = html[: html.index('<div id="page-body"')]
                tag = before[before.rindex("<div") :]
                self.assertIn(PAGE_WIDTH_CLASSES[width], tag)

    def test_each_width_reaches_the_dialog_answer(self):
        for width in PAGE_WIDTHS:
            with self.subTest(width=width):
                response = render_page(
                    self._request(DIALOG_HEADERS), Div()["Body"], width=width
                )
                self.assertEqual(json.loads(response.content)["width"], width)

    def test_the_panel_states_a_cap_per_width(self):
        html = str(FormDialogHost())
        panel = _opening_tag(html, MODAL_ATTRIBUTES["panel"])
        self.assertIn(f'{PAGE_WIDTH_ATTRIBUTE}="form"', panel)
        for width in PAGE_WIDTHS:
            with self.subTest(width=width):
                self.assertIn(
                    f"data-[page-width={width}]:{PAGE_WIDTH_CLASSES[width]}", panel
                )

    def test_each_route_states_its_width(self):
        self.client.force_login(self.user)
        game = create_tracked_game(self.user.library, "Outer Wilds")
        routes: list[tuple[str, list[object], PageWidth]] = [
            ("games:add_device", [], "form"),
            ("games:add_platform", [], "form"),
            ("games:add_playthrough", [], "form"),
            ("games:add_session", [], "form"),
            ("games:remove_game", [game.pk], "form"),
            ("games:add_game", [], "form"),
            ("games:edit_game", [game.pk], "form"),
            ("games:list_games", [], "full"),
            ("games:stats_alltime", [], "full"),
        ]
        for name, args, width in routes:
            with self.subTest(route=name):
                answer = _dialog_get(self.client, reverse(name, args=args)).json()
                self.assertEqual(answer["width"], width)

    def test_a_confirmation_widens_for_a_choice(self):
        self.assertEqual(confirmation_width(None), "form")
        self.assertEqual(confirmation_width(Div()["Pick one"]), "wide")

    def test_form_bodies_set_no_cap_of_their_own(self):
        request = self._request()
        bodies = {
            "AddForm": AddForm(forms.Form(), request=request),
            "ConfirmPage": ConfirmPage(
                title="Remove?", post_url="/", csrf_token="t", cancel_url="/"
            ),
        }
        for name, body in bodies.items():
            with self.subTest(body=name):
                self.assertNotIn("max-w-", str(body))


class AnswerCodegenTest(SimpleTestCase):
    def test_an_optional_key_is_optional(self):
        module = render_filter_metadata_module([ToastPayload])
        self.assertIn("  action?: ToastAction;", module)
        self.assertIn("  message: string;", module)

    def test_the_answers_are_generated(self):
        module = form_dialog_module()
        self.assertIn('kind: "page";', module)
        self.assertIn('kind: "done";', module)
        self.assertIn('kind: "continue";', module)
        self.assertIn('kind: "created";', module)
        self.assertIn("export interface CreatedOption {", module)
        self.assertIn(f'FORM_DIALOG_HEADER: string = "{FORM_DIALOG_HEADER}"', module)


class _IdReferences(HTMLParser):
    """Every id, and every attribute naming one."""

    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.attributes: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if value is None:
                continue
            if name == "id":
                self.ids.add(value)
            else:
                self.attributes.append((name, value))

    def references(self) -> set[str]:
        return {
            name
            for name, value in self.attributes
            if name not in _NOT_REFERENCES
            and (set(value.split()) & self.ids or value.lstrip("#") in self.ids)
        }


#: Attributes whose value may equal an id by chance.
_NOT_REFERENCES = {"name", "value", "class", "title", "aria-label", "placeholder"}

#: Pages a form dialog presents.
_FORM_ROUTES = (
    "games:add_device",
    "games:add_platform",
    "games:add_game",
    "games:add_session",
    "games:add_playthrough",
)


class IdReferenceContractTest(TestCase):
    """The prefix rewrite knows every id reference."""

    def setUp(self) -> None:
        user = User.objects.create_superuser(
            username="refs", email="refs@example.com", password="refs"
        )
        self.client.force_login(user)

    def test_every_reference_attribute_is_rewritten(self):
        known = {*FORM_DIALOG_ID_ATTRIBUTES, *FORM_DIALOG_ID_LIST_ATTRIBUTES, "href"}
        for route in _FORM_ROUTES:
            with self.subTest(route=route):
                parser = _IdReferences()
                parser.feed(self.client.get(reverse(route)).content.decode())
                # Labels prove the parser sees references.
                self.assertIn("for", parser.references())
                self.assertLessEqual(parser.references(), known)
