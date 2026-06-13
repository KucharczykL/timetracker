import unittest
from typing import TypedDict

from common.components import custom_element, render
from common.components.custom_elements import (
    ElementSpec,
    _ts_for_spec,
    register_element,
)


class SampleProps(TypedDict):
    game_id: int
    status: str
    is_on: bool


class CustomElementBuilderTest(unittest.TestCase):
    def test_serializes_props_to_kebab_attributes(self):
        html = render(
            custom_element("x-sample", {"game_id": 3, "status": "f"}, children=["hi"])
        )
        self.assertIn("<x-sample", html)
        self.assertIn('game-id="3"', html)
        self.assertIn('status="f"', html)
        self.assertIn(">hi</x-sample>", html)

    def test_declares_compiled_module_media(self):
        from common.components import collect_media

        node = custom_element("x-sample", {"game_id": 3})
        self.assertEqual(collect_media(node).js, ("dist/elements/x-sample.js",))


class CodegenTest(unittest.TestCase):
    def test_emits_interface_and_reader(self):
        spec = ElementSpec("x-sample", "XSample", SampleProps)
        ts = _ts_for_spec(spec)
        self.assertIn("export interface XSampleProps {", ts)
        self.assertIn("gameId: number;", ts)
        self.assertIn("status: string;", ts)
        self.assertIn("isOn: boolean;", ts)
        self.assertIn(
            "export function readXSampleProps(el: HTMLElement): XSampleProps", ts
        )
        self.assertIn('Number(el.getAttribute("game-id"))', ts)
        self.assertIn('el.getAttribute("status") ?? ""', ts)
        self.assertIn('el.getAttribute("is-on") === "true"', ts)


class RegistryTest(unittest.TestCase):
    def test_register_adds_spec(self):
        from common.components.custom_elements import ELEMENT_REGISTRY

        before = len(ELEMENT_REGISTRY)
        register_element("x-reg-test", "XRegTest", SampleProps)
        self.assertEqual(len(ELEMENT_REGISTRY), before + 1)
        self.assertEqual(ELEMENT_REGISTRY[-1].tag, "x-reg-test")
