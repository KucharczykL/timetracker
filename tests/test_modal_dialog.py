"""The dialog the modal layer attaches to."""

from pathlib import Path

from django.test import SimpleTestCase

from common.components import (
    BottomSheet,
    ControlButton,
    ModalDialog,
    ModalPanel,
    ModalPanelHeader,
)
from common.components.modal import (
    _MODAL_DIALOG_CLASS,
    _MODAL_PANEL_CLASS,
    MODAL_ATTRIBUTES,
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
        self.assertIn("hidden", html[trail : html.index(">", trail)])


class ModalPanelTest(SimpleTestCase):
    def test_carries_the_marker_and_the_step(self):
        html = str(ModalPanel(class_="extra"))
        self.assertIn(f'{MODAL_ATTRIBUTES["panel"]}=""', html)
        self.assertIn("extra", html)
        self.assertIn("origin-top", html)

    def test_the_step_names_the_stamp_and_the_properties(self):
        """Tailwind needs literals; they must match the layer."""
        self.assertIn(f"{MODAL_ATTRIBUTES['depth']}:", _MODAL_PANEL_CLASS)
        for name in ("--modal-shift", "--modal-reserve", "--modal-depth"):
            self.assertIn(name, _MODAL_PANEL_CLASS)

    def test_the_step_never_takes_the_sheets_translate(self):
        self.assertIn("[transform:", _MODAL_PANEL_CLASS)
        self.assertNotIn("translate-y-", _MODAL_PANEL_CLASS)
        self.assertNotIn("scale-", _MODAL_PANEL_CLASS)

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
        self.assertNotIn("motion-safe:transition-transform", tag)
