import unittest
from typing import TypedDict

from common.components import custom_element_builder, render
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
        x_sample = custom_element_builder("x-sample")
        html = render(x_sample(game_id=3, status="f")["hi"])
        self.assertIn("<x-sample", html)
        self.assertIn('game-id="3"', html)
        self.assertIn('status="f"', html)
        self.assertIn(">hi</x-sample>", html)

    def test_declares_compiled_module_media(self):
        from common.components import collect_media

        x_sample = custom_element_builder("x-sample")
        node = x_sample(game_id=3)
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


class DropdownRenderTest(unittest.TestCase):
    def test_navbar_dropdown_emits_tag_panel_and_fix(self):
        from common.components import Dropdown, DropdownLinkItem, collect_media, render

        node = Dropdown(
            label="New",
            id="dropdownNavbarNew",
            placement="bottom-end",
            items=[
                DropdownLinkItem("/games/add/", "Game"),
                DropdownLinkItem("/sessions/add/", "Session", current=True),
            ],
        )
        html = render(node)
        self.assertIn("<dropdown-menu", html)
        self.assertIn('placement="bottom-end"', html)
        self.assertIn('submenu="false"', html)
        self.assertIn('id="dropdownNavbarNewLink"', html)
        self.assertIn('aria-haspopup="menu"', html)
        self.assertIn('aria-controls="dropdownNavbarNew"', html)
        self.assertIn('role="menu"', html)
        self.assertIn("hidden", html)
        self.assertIn('role="menuitem"', html)
        self.assertIn('aria-current="page"', html)
        # #46 fix: panel clips its corners and the list has no vertical padding.
        self.assertIn("overflow-hidden", html)
        self.assertNotIn('<ul class="py-2', html)
        self.assertIn("dist/elements/dropdown-menu.js", collect_media(node).js)

    def test_split_button_primary_slot(self):
        from common.components import (
            Dropdown,
            DropdownActionItem,
            DropdownLinkItem,
            Span,
            render,
        )

        primary = Span(class_="rounded-s-lg")["Played 3 times"]
        node = Dropdown(
            label="",
            id="played",
            outline=True,
            primary=primary,
            items=[
                DropdownLinkItem("/add/", "Add playthrough…"),
                DropdownActionItem("Played +1", attributes=[("data-add-play", "")]),
            ],
        )
        html = render(node)
        self.assertIn("rounded-s-lg", html)
        self.assertIn("rounded-e-lg", html)  # toggle gains it in split mode
        self.assertIn("inline-flex items-stretch", html)
        self.assertIn("data-add-play", html)
        self.assertIn("border", html)  # outlined toggle + panel

    def test_unified_panel_light_white_dark_frosted(self):
        from common.components import Dropdown, DropdownLinkItem, render

        # Menu-like (no outline): white in light, frosted in dark, borderless.
        menu = render(Dropdown(label="M", id="m", items=[DropdownLinkItem("/a/", "A")]))
        self.assertIn("bg-white", menu)
        self.assertIn("dark:bg-gray-800/20", menu)
        self.assertIn("dark:backdrop-blur-lg", menu)
        self.assertIn("overflow-hidden", menu)  # #46 fix kept
        self.assertIn("shadow-sm", menu)
        self.assertNotIn("border-gray-200", menu)  # borderless menu

        # Button-like (outline): same panel + a border on toggle and panel.
        outlined = render(
            Dropdown(
                label="B", id="b", outline=True, items=[DropdownLinkItem("/a/", "A")]
            )
        )
        self.assertIn("dark:bg-gray-800/20", outlined)  # same frosted-dark panel
        self.assertIn("border-gray-200", outlined)  # outlined

    def test_submenu_item(self):
        from common.components import (
            Dropdown,
            DropdownLinkItem,
            DropdownSubmenu,
            render,
        )

        node = Dropdown(
            label="Menu",
            id="navbarMenu",
            items=[
                DropdownSubmenu(
                    "Game",
                    id="navbarMenuGame",
                    items=[
                        DropdownLinkItem("/games/add/", "Add game"),
                        DropdownLinkItem("/games/", "List games"),
                    ],
                ),
            ],
        )
        html = render(node)
        # The submenu toggle is itself a menuitem with a popup, nested in a
        # right-start <dropdown-menu>.
        self.assertEqual(html.count("<dropdown-menu"), 2)
        self.assertIn('id="navbarMenuGameLink"', html)
        self.assertIn('aria-haspopup="menu"', html)
        self.assertIn('placement="right-start"', html)
        self.assertIn('submenu="true"', html)
        self.assertIn("Add game", html)

    def test_check_and_divider_items(self):
        from common.components import (
            Dropdown,
            DropdownCheckItem,
            DropdownDivider,
            render,
        )

        node = Dropdown(
            label="Filter",
            id="filter",
            items=[
                DropdownCheckItem("Emulated", checked=True),
                DropdownDivider(),
                DropdownCheckItem("Mastered", checked=False),
            ],
        )
        html = render(node)
        self.assertIn('role="menuitemcheckbox"', html)
        self.assertIn('aria-checked="true"', html)
        self.assertIn('aria-checked="false"', html)
        self.assertIn('role="separator"', html)


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
