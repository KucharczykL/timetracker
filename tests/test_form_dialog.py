"""The form dialog's server half: links, host, layout stamps."""

import re

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from common.components import (
    BottomSheet,
    ControlButton,
    DropdownLinkItem,
    FormDialogHost,
    form_dialog_link,
)
from common.components.form_dialog import (
    FORM_DIALOG_ATTRIBUTE,
    FORM_DIALOG_CHROME_VALUES,
    FORM_DIALOG_PARTS,
)
from games.management.commands.gen_element_types import form_dialog_module


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
        template_start = html.index("<template")
        self.assertLess(template_start, html.index("<dialog"))
        self.assertLess(html.index("</dialog>"), html.index("</template>"))

    def test_the_template_names_every_part(self):
        html = str(FormDialogHost())
        for part in FORM_DIALOG_PARTS.values():
            self.assertIn(f"{part}=", html)

    def test_the_dialog_is_named_by_its_title(self):
        html = str(FormDialogHost())
        title_id = re.search(r'aria-labelledby="([^"]+)"', html)
        assert title_id is not None
        self.assertIn(f'id="{title_id.group(1)}"', html)
        self.assertIn('data-modal-dismiss=""', html)

    def test_the_generated_module_states_every_value(self):
        module = form_dialog_module()
        self.assertIn(f'"{FORM_DIALOG_ATTRIBUTE}"', module)
        for chrome, value in FORM_DIALOG_CHROME_VALUES.items():
            self.assertIn(f'"{chrome}": "{value}"', module)
        for part, attribute in FORM_DIALOG_PARTS.items():
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


class LayoutStampTest(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_superuser(
            username="stamp", email="stamp@example.com", password="stamp"
        )
        self.client.force_login(self.user)

    def _main_container(self, html: str) -> str:
        return _opening_tag(html, 'id="main-container"')

    def test_a_list_page_is_read_only(self):
        html = self.client.get(reverse("games:list_devices")).content.decode()
        tag = self._main_container(html)
        self.assertIn("data-read-only", tag)
        self.assertIn('tabindex="-1"', tag)
        self.assertIn("<form-dialog", html)
        self.assertIn('id="navbar"', html)

    def test_a_form_page_is_not_read_only(self):
        html = self.client.get(reverse("games:add_device")).content.decode()
        tag = self._main_container(html)
        self.assertNotIn("data-read-only", tag)
        self.assertIn("<form-dialog", html)

    def test_the_page_title_is_stamped_raw(self):
        html = self.client.get(reverse("games:add_device")).content.decode()
        title = re.search(r"<title>Timetracker - ([^<]*)</title>", html)
        assert title is not None
        self.assertIn(f'data-page-title="{title.group(1)}"', self._main_container(html))
