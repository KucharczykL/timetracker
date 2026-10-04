"""The dialog the modal layer attaches to."""

from pathlib import Path

from django.test import SimpleTestCase

from common.components import BottomSheet, ControlButton, ModalDialog
from common.components.modal import _MODAL_DIALOG_CLASS, MODAL_ATTRIBUTES

GENERATED_MODULE = Path("ts/generated/modal-attributes.ts")


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
