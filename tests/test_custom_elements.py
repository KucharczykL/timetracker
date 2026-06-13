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


class GameStatusSelectorRenderTest(unittest.TestCase):
    def test_emits_tag_props_and_media(self):
        from types import SimpleNamespace

        from common.components import GameStatusSelector, collect_media, render

        game = SimpleNamespace(id=7, status="f", get_status_display=lambda: "Finished")
        node = GameStatusSelector(game, [("u", "Unplayed"), ("f", "Finished")], "tok")
        html = render(node)
        self.assertIn("<game-status-selector", html)
        self.assertIn('game-id="7"', html)
        self.assertIn('status="f"', html)
        self.assertIn('csrf="tok"', html)
        self.assertIn("data-option", html)
        self.assertIn('data-value="u"', html)
        self.assertNotIn("x-data", html)  # no Alpine left
        self.assertIn("dist/elements/game-status-selector.js", collect_media(node).js)


class SessionDeviceSelectorRenderTest(unittest.TestCase):
    def test_emits_tag_and_options(self):
        from types import SimpleNamespace

        from common.components import SessionDeviceSelector, render

        session = SimpleNamespace(id=4, device=SimpleNamespace(name="Desktop"))
        devices = [
            SimpleNamespace(id=1, name="Desktop"),
            SimpleNamespace(id=2, name="Deck"),
        ]
        html = render(SessionDeviceSelector(session, devices, "tok"))
        self.assertIn("<session-device-selector", html)
        self.assertIn('session-id="4"', html)
        self.assertIn('data-value="2"', html)
        self.assertNotIn("x-data", html)
