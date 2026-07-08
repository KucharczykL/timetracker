import unittest
from html.parser import HTMLParser
from typing import TypedDict

from common.components import custom_element_builder, render
from common.components.custom_elements import (
    ElementSpec,
    _ts_for_spec,
    register_element,
)


def _option_selection(html: str) -> dict[str | None, str | None]:
    """Map each ``[data-option]`` element's ``data-value`` to its
    ``aria-selected``, parsed from the markup so assertions don't couple to
    attribute emission order."""

    class _Options(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.found: dict[str | None, str | None] = {}

        def handle_starttag(
            self, tag: str, attrs: list[tuple[str, str | None]]
        ) -> None:
            attributes = dict(attrs)
            if "data-option" in attributes:
                self.found[attributes.get("data-value")] = attributes.get(
                    "aria-selected"
                )

    parser = _Options()
    parser.feed(html)
    return parser.found


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

    def test_register_rejects_non_typeddict(self):
        # The TypedDictClass alias is transparent, so this guard is the only
        # enforcement that a registered props class is actually a TypedDict.
        from common.components.custom_elements import ELEMENT_REGISTRY

        before = len(ELEMENT_REGISTRY)
        with self.assertRaises(TypeError):
            register_element("x-bad", "XBad", dict)
        self.assertEqual(len(ELEMENT_REGISTRY), before)  # nothing registered


class GameStatusSelectorRenderTest(unittest.TestCase):
    def test_emits_listbox_and_patch_config(self):
        from types import SimpleNamespace
        from common.components import GameStatusSelector, render

        game = SimpleNamespace(id=7, status="f", get_status_display=lambda: "Finished")
        html = render(
            GameStatusSelector(game, [("u", "Unplayed"), ("f", "Finished")], "tok")
        )
        self.assertIn('behavior="select"', html)
        self.assertIn('role="listbox"', html)
        self.assertIn('data-patch-url="/api/games/7/status"', html)
        self.assertIn('data-body-key="status"', html)
        self.assertIn('data-value="u"', html)
        self.assertNotIn("<game-status-selector", html)  # element retired


class ContractStampingTest(unittest.TestCase):
    def test_core_stamps_trigger_and_target_contracts(self):
        from common.components import Dropdown, DropdownLinkItem, DropdownMenuPanel
        from common.components import render
        from common.components.core import Element

        trigger = Element("button", [("class", "look")], ["Open"])
        target = DropdownMenuPanel(items=[DropdownLinkItem("/a/", "A")])
        html = render(Dropdown(trigger_element=trigger, target_element=target, id="d"))
        # Behavioral hooks + ARIA wiring stamped by the core.
        self.assertIn('data-toggle=""', html)
        self.assertIn('id="dLink"', html)
        self.assertIn('aria-controls="d"', html)
        self.assertIn('aria-expanded="false"', html)
        self.assertIn('data-menu=""', html)
        self.assertIn('id="d"', html)
        self.assertIn("hidden", html)
        self.assertIn('aria-labelledby="dLink"', html)
        self.assertIn('class="look"', html)  # caller's look preserved
        self.assertIn('submenu="false"', html)
        # No menu semantics injected by the generic core.
        self.assertNotIn("aria-haspopup", html.split("<div")[0])  # not on the trigger

    def test_reserved_attr_conflict_warns(self):
        from common.components import DropdownContractWarning, render
        from common.components.custom_elements import _stamp_trigger_contract
        from common.components.core import Element

        trigger = Element("button", [("aria-expanded", "true"), ("class", "c")])
        with self.assertWarns(DropdownContractWarning):
            stamped = _stamp_trigger_contract(trigger, "x")
        html = render(stamped)
        self.assertEqual(html.count("aria-expanded"), 1)  # de-duped
        self.assertIn('aria-expanded="false"', html)  # contract value wins
        self.assertIn('class="c"', html)  # non-reserved attr preserved

    def test_aria_label_suppresses_auto_labelledby(self):
        from common.components import DropdownMenuPanel, render
        from common.components.custom_elements import _stamp_target_contract

        labelled = _stamp_target_contract(
            DropdownMenuPanel(items=[], aria_label="Playthrough actions"), "p"
        )
        html = render(labelled)
        self.assertIn('aria-label="Playthrough actions"', html)
        self.assertNotIn("aria-labelledby", html)  # explicit label wins

        auto = _stamp_target_contract(DropdownMenuPanel(items=[]), "p")
        self.assertIn('aria-labelledby="pLink"', render(auto))


class DropdownMenuPanelTest(unittest.TestCase):
    def test_renders_role_menu_panel(self):
        from common.components import DropdownLinkItem, DropdownMenuPanel, render

        html = render(DropdownMenuPanel(items=[DropdownLinkItem("/a/", "A")]))
        self.assertIn('role="menu"', html)
        self.assertIn("shadow-sm", html)  # the single shadowed panel look
        # Clips sideways; scrolls vertically once the positioner caps the height.
        self.assertIn("overflow-x-hidden", html)
        self.assertIn("overflow-y-auto", html)
        self.assertIn("<ul", html)
        self.assertIn('role="menuitem"', html)
        # ul/li carry role=presentation so menu→menuitem ownership isn't interrupted
        self.assertIn('<ul role="presentation"', html)
        self.assertIn('<li role="presentation"', html)


class DropdownWrapperTest(unittest.TestCase):
    def test_menu_dropdown_emits_tag_and_menu_trigger(self):
        from common.components import (
            DropdownLinkItem,
            MenuDropdown,
            collect_media,
            render,
        )

        node = MenuDropdown(
            label="Menu",
            id="navbarMenu",
            placement="bottom-center",
            items=[DropdownLinkItem("/games/", "Game", current=True)],
        )
        html = render(node)
        self.assertIn("<drop-down ", html)
        self.assertIn('placement="bottom-center"', html)
        self.assertIn('behavior="menu"', html)
        self.assertIn('id="navbarMenuLink"', html)
        self.assertIn('aria-haspopup="menu"', html)  # menu semantics from the wrapper
        self.assertIn('role="menu"', html)
        self.assertIn('aria-current="page"', html)
        self.assertIn("dist/elements/drop-down.js", collect_media(node).js)

    def test_button_dropdown_uses_control_button_trigger(self):
        from common.components import ButtonDropdown, DropdownLinkItem, render

        html = render(
            ButtonDropdown(
                label="Actions", id="acts", items=[DropdownLinkItem("/a/", "A")]
            )
        )
        self.assertIn('aria-haspopup="menu"', html)
        self.assertIn('id="actsLink"', html)
        self.assertIn("rounded-base", html)  # ControlButton styling

    def test_split_button_groups_primary_with_caret(self):
        from common.components import (
            DropdownActionItem,
            DropdownLinkItem,
            SplitButtonDropdown,
            Span,
            render,
        )

        primary = Span(class_="rounded-s-lg")["Played 3 times"]
        html = render(
            SplitButtonDropdown(
                primary=primary,
                id="played",
                aria_label="Playthrough actions",
                items=[
                    DropdownLinkItem("/add/", "Add playthrough…"),
                    DropdownActionItem(data_add_play="")["Played +1"],
                ],
            )
        )
        self.assertIn("inline-flex items-stretch", html)  # the flex group
        self.assertIn("rounded-s-lg", html)  # caller's primary
        self.assertIn("rounded-e-lg", html)  # the caret
        self.assertIn("data-add-play", html)
        self.assertIn('aria-label="Playthrough actions"', html)
        self.assertNotIn("aria-labelledby", html)  # icon-only caret → explicit label


class DropdownSubmenuTest(unittest.TestCase):
    def test_submenu_item(self):
        from common.components import (
            Dropdown,
            DropdownLinkItem,
            DropdownMenuPanel,
            DropdownSubmenu,
            render,
        )
        from common.components.core import Element

        node = Dropdown(
            trigger_element=Element("button", [], ["Menu"]),
            target_element=DropdownMenuPanel(
                items=[
                    DropdownSubmenu(
                        "Game",
                        id="navbarMenuGame",
                        items=[
                            DropdownLinkItem("/games/add/", "Add game"),
                            DropdownLinkItem("/games/", "List games"),
                        ],
                    ),
                ]
            ),
            id="navbarMenu",
        )
        html = render(node)
        # The submenu trigger is itself a menuitem with a popup, nested in a
        # right-start <drop-down>.
        self.assertEqual(html.count("<drop-down "), 2)
        self.assertIn('id="navbarMenuGameLink"', html)
        self.assertIn('role="menuitem"', html)
        self.assertIn('aria-haspopup="menu"', html)
        self.assertIn('placement="right-start"', html)
        self.assertIn('submenu="true"', html)
        self.assertIn("Add game", html)

    def test_placement_override(self):
        from common.components import DropdownLinkItem, DropdownSubmenu, render

        html = render(
            DropdownSubmenu(
                "Game",
                id="g",
                placement="bottom-start",
                items=[DropdownLinkItem("/a/", "A")],
            )
        )
        self.assertIn('placement="bottom-start"', html)
        self.assertIn('submenu="true"', html)  # intrinsic, unaffected

    def test_check_and_divider_items(self):
        from common.components import (
            DropdownCheckItem,
            DropdownDivider,
            DropdownMenuPanel,
            render,
        )

        html = render(
            DropdownMenuPanel(
                items=[
                    DropdownCheckItem("Emulated", checked=True),
                    DropdownDivider(),
                    DropdownCheckItem("Mastered", checked=False),
                ]
            )
        )
        self.assertIn('role="menuitemcheckbox"', html)
        self.assertIn('aria-checked="true"', html)
        self.assertIn('aria-checked="false"', html)
        self.assertIn('role="separator"', html)


class SessionDeviceSelectorRenderTest(unittest.TestCase):
    def test_emits_listbox_and_numeric_patch(self):
        from types import SimpleNamespace
        from common.components import SessionDeviceSelector, render

        session = SimpleNamespace(id=4, device=SimpleNamespace(id=2, name="Deck"))
        devices = [
            SimpleNamespace(id=1, name="Desktop"),
            SimpleNamespace(id=2, name="Deck"),
        ]
        html = render(SessionDeviceSelector(session, devices, "tok"))
        self.assertIn('behavior="select"', html)
        self.assertIn('data-patch-url="/api/session/4/device"', html)
        self.assertIn('data-body-key="device_id"', html)
        self.assertIn('data-numeric="true"', html)
        self.assertIn('data-value="2"', html)

    def test_clear_option_present(self):
        from types import SimpleNamespace
        from common.components import SessionDeviceSelector, render

        session = SimpleNamespace(id=4, device=SimpleNamespace(id=2, name="Deck"))
        html = render(
            SessionDeviceSelector(session, [SimpleNamespace(id=2, name="Deck")], "tok")
        )
        self.assertIn('data-value=""', html)
        self.assertIn("No device", html)

    def test_null_device_selects_clear_option_and_labels_no_device(self):
        from types import SimpleNamespace
        from common.components import SessionDeviceSelector, render

        session = SimpleNamespace(id=4, device=None)
        html = render(
            SessionDeviceSelector(session, [SimpleNamespace(id=2, name="Deck")], "tok")
        )
        # The clear option is the aria-selected one, and the trigger label
        # coalesces to "No device".
        self.assertEqual(_option_selection(html), {"": "true", "2": "false"})
        self.assertIn("No device", html)


class SelectDropdownRenderTest(unittest.TestCase):
    def test_renders_listbox_with_select_behavior(self):
        from common.components import SelectDropdown, render
        from common.components.custom_elements import SelectOption

        html = render(
            SelectDropdown(
                current_label="Played",
                options=[
                    SelectOption("u", "Unplayed", False),
                    SelectOption("f", "Finished", True),
                ],
                id="game-7-status",
                patch_url="/api/games/7/status",
                body_key="status",
                event="status-changed",
                csrf="tok",
            )
        )
        self.assertIn('behavior="select"', html)
        self.assertIn('role="listbox"', html)
        self.assertIn('role="option"', html)
        self.assertIn('aria-haspopup="listbox"', html)
        self.assertIn('data-patch-url="/api/games/7/status"', html)
        self.assertIn('data-body-key="status"', html)
        self.assertIn('data-event="status-changed"', html)
        self.assertIn('data-value="f"', html)
        self.assertIn('aria-selected="true"', html)  # the current option
        self.assertIn("data-label", html)  # the toggle's swappable label

    def test_numeric_flag_sets_data_numeric(self):
        from common.components import SelectDropdown, render
        from common.components.custom_elements import SelectOption

        html = render(
            SelectDropdown(
                current_label="Deck",
                options=[SelectOption("2", "Deck", True)],
                id="session-4-device",
                patch_url="/api/session/4/device",
                body_key="device_id",
                event="device-changed",
                csrf="t",
                numeric=True,
            )
        )
        self.assertIn('data-numeric="true"', html)
