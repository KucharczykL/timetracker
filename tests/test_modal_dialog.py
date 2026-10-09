"""The dialog the modal layer attaches to."""

import re
from pathlib import Path

from django.test import SimpleTestCase

from common.components import (
    BottomSheet,
    ControlButton,
    ModalDialog,
    ModalPanel,
    ModalPanelHeader,
)
from common.components.elements import Span
from common.components.form_dialog import FormDialogHost
from common.components.modal import (
    _CENTRED_PANEL_MOTION_CLASS,
    _MODAL_DIALOG_CLASS,
    _MODAL_PANEL_CLASS,
    _SHEET_PANEL_MOTION_CLASS,
    MODAL_ATTRIBUTES,
)

#: The properties ts/elements/modal-stack.ts writes.
STACK_PROPERTIES = re.findall(
    r'"(--modal-[a-z]+)"',
    Path("ts/elements/modal-stack.ts")
    .read_text(encoding="utf-8")
    .split("STACK_PROPERTIES = [", 1)[1]
    .split("]", 1)[0],
)
GENERATED_MODULE = Path("ts/generated/modal-attributes.ts")
BASE_CSS = Path("games/static/base.css")


def _dialog_tag(html: str) -> str:
    start = html.index("<dialog")
    return html[start : html.index(">", start) + 1]


class ModalDialogTest(SimpleTestCase):
    def test_carries_the_attribute_and_the_classes_together(self):
        tag = _dialog_tag(str(ModalDialog()))
        self.assertIn('data-modal=""', tag)
        self.assertIn("backdrop:bg-dark-backdrop/70", tag)
        self.assertIn("open:items-center", tag)

    def test_a_sheet_aligns_to_the_bottom(self):
        tag = _dialog_tag(
            str(
                BottomSheet(
                    trigger_element=ControlButton()["Sections"].as_element(),
                    title="Sections",
                    children=[],
                    id="sheet",
                )
            )
        )
        self.assertIn('data-modal=""', tag)
        self.assertIn("open:items-end", tag)
        self.assertNotIn("open:items-center", tag)

    def test_the_dim_classes_name_the_stamped_attributes(self):
        """Tailwind needs literals; they must match the layer."""
        for role in ("covered", "over"):
            self.assertIn(f"{MODAL_ATTRIBUTES[role]}:", _MODAL_DIALOG_CLASS)

    def test_the_generated_module_states_every_attribute(self):
        module = GENERATED_MODULE.read_text(encoding="utf-8")
        for role, attribute in MODAL_ATTRIBUTES.items():
            self.assertIn(f'"{role}": "{attribute}"', module)


def _sheet_html() -> str:
    return str(
        BottomSheet(
            trigger_element=ControlButton()["Sections"].as_element(),
            title="Sections",
            children=[],
            id="sheet",
        )
    )


class ModalPanelHeaderTest(SimpleTestCase):
    def test_the_header_is_compact(self):
        html = str(ModalPanelHeader("Title", title_id="t"))
        self.assertIn(f'{MODAL_ATTRIBUTES["header"]}=""', html)
        self.assertIn("py-1.5 pl-4 pr-1.5", html)
        self.assertNotIn("py-3", html)
        self.assertIn("size-8", html)

    def test_the_plain_header_is_compact_too(self):
        html = str(
            ModalPanelHeader("Title", title_id="t", close_label=None, divided=False)
        )
        self.assertIn("py-1.5", html)
        self.assertNotIn("pt-4", html)

    def test_a_hidden_trail_sits_above_the_title(self):
        html = str(ModalPanelHeader("Title", title_id="t"))
        trail = html.index(f'{MODAL_ATTRIBUTES["trail"]}=""')
        self.assertLess(trail, html.index('id="t"'))
        self.assertIn(' hidden=""', html[trail : html.index(">", trail)])


class ModalPanelTest(SimpleTestCase):
    def test_carries_the_marker_and_the_step(self):
        html = str(ModalPanel(class_="extra"))
        self.assertIn(f'{MODAL_ATTRIBUTES["panel"]}=""', html)
        self.assertIn("extra", html)
        self.assertIn("origin-top", html)

    def test_the_step_names_the_stamp_and_the_properties(self):
        """Tailwind needs literals; they must match the layer."""
        self.assertIn(f"{MODAL_ATTRIBUTES['depth']}:", _MODAL_PANEL_CLASS)
        # The depth reaches CSS as data-modal-depth, not as a property.
        for name in STACK_PROPERTIES:
            if name != "--modal-depth":
                self.assertIn(name, _MODAL_PANEL_CLASS)

    def test_the_step_never_takes_the_sheets_translate(self):
        self.assertIn("[transform:", _MODAL_PANEL_CLASS)
        self.assertNotIn("translate-y-", _MODAL_PANEL_CLASS)
        self.assertNotIn("scale-", _MODAL_PANEL_CLASS)

    def test_the_sheet_slide_is_its_own_transition(self):
        """The sheet controller waits on the slide's own transition."""
        transitions = re.search(r"transition-\[([^\]]+)\]", _SHEET_PANEL_MOTION_CLASS)
        assert transitions
        self.assertEqual(transitions.group(1).split(","), ["translate", "opacity"])

    def test_the_depth_cue_never_dims_the_panel(self):
        """The scrim is the panel's ::after; the panel itself stays opaque."""
        self.assertNotRegex(_MODAL_PANEL_CLASS, r"(?<!after:)opacity-")
        self.assertNotIn("brightness", _MODAL_PANEL_CLASS)
        self.assertNotIn("filter", _MODAL_PANEL_CLASS)
        self.assertIn("after:opacity-[var(--modal-scrim", _MODAL_PANEL_CLASS)

    def test_no_motion_class_is_safe_only(self):
        """Reduced motion crossfades; it does not drop motion."""
        for name in (
            _MODAL_PANEL_CLASS,
            _CENTRED_PANEL_MOTION_CLASS,
            _SHEET_PANEL_MOTION_CLASS,
        ):
            self.assertNotIn("motion-safe:", name)

    def test_the_built_css_holds_the_step(self):
        """base.css is built; run `make css` first."""
        css = BASE_CSS.read_text(encoding="utf-8")
        for rule in (
            "transform: translateY(var(--modal-shift)) scale(",
            "margin-top: var(--modal-reserve,0px)",
            "max-height: calc(100dvh - 2rem - var(--modal-reserve,0px))",
        ):
            self.assertIn(rule, css)

    def test_the_sheet_panel_is_a_modal_panel(self):
        html = _sheet_html()
        start = html.index("data-sheet-panel")
        tag = html[html.rindex("<", 0, start) : html.index(">", start)]
        self.assertIn(f'{MODAL_ATTRIBUTES["panel"]}=""', tag)
        self.assertIn("translate-y-full", tag)
        self.assertNotIn("motion-safe:", tag)


#: Every module that builds a ModalDialog.
_MODAL_BUILDERS = {
    Path("common/components/custom_elements.py"),
    Path("common/components/form_dialog.py"),
}


class EveryModalSteps(SimpleTestCase):
    """A modal without a panel never steps back."""

    def test_no_other_module_builds_a_modal(self):
        builders = {
            path
            for root in ("common", "games")
            for path in Path(root).rglob("*.py")
            if "ModalDialog(" in path.read_text(encoding="utf-8")
            and path != Path("common/components/modal.py")
        }
        self.assertEqual(builders, _MODAL_BUILDERS)

    def test_each_built_modal_has_a_panel_and_a_header(self):
        html = str(FormDialogHost()) + _sheet_html()
        dialogs = html.split("<dialog")[1:]
        self.assertEqual(len(dialogs), 3)
        for dialog in dialogs:
            body = dialog.split("</dialog>", 1)[0]
            self.assertIn(f'{MODAL_ATTRIBUTES["panel"]}=""', body)
            self.assertIn(f'{MODAL_ATTRIBUTES["header"]}=""', body)


class ModalPanelLeadingTest(SimpleTestCase):
    def test_a_leading_control_precedes_the_title(self):
        html = str(
            ModalPanelHeader(
                "Title",
                title_id="t",
                leading=Span(class_="lead")["Back"],
            )
        )
        self.assertIn('class="lead"', html)
        self.assertLess(html.index("Back"), html.index("Title"))
