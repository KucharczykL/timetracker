"""Every dropdown panel scrolls inside its surface."""

from html.parser import HTMLParser
from zoneinfo import ZoneInfo

import pytest

from common.components import (
    DROPDOWN_ITEM_ACTIVE,
    Column,
    ColumnPicker,
    ComboboxDropdown,
    DropdownActionItem,
    DropdownMenuPanel,
    DropdownPanel,
    ListboxPanel,
    QuickFilterBar,
    Safe,
    Span,
)
from common.components.custom_elements import SelectOption
from common.components.primitives import _selection_actions_slot
from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DateTimePresentation,
)


class _Tree(HTMLParser):
    """Each element's attributes and its element children."""

    VOID = frozenset({"input", "br", "img", "hr", "meta", "link"})

    def __init__(self) -> None:
        super().__init__()
        self.root: dict = {"attributes": {}, "children": []}
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = {"tag": tag, "attributes": dict(attrs), "children": []}
        self.stack[-1]["children"].append(node)
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_endtag(self, tag):
        if tag not in self.VOID:
            self.stack.pop()


def _elements(html: str) -> list[dict]:
    tree = _Tree()
    tree.feed(html)
    found = []

    def walk(node):
        found.append(node)
        for child in node["children"]:
            walk(child)

    walk(tree.root)
    return found


def _panels(html: str) -> list[dict]:
    """Elements whose one child is the scroller."""
    return [
        element
        for element in _elements(html)
        if any(
            "data-menu-scroll" in child["attributes"] for child in element["children"]
        )
    ]


def _column_picker() -> str:
    return str(
        ColumnPicker(
            [Column("Year", "year", key="year")],
            (),
            post_url="/columns/",
            csrf_input=Safe("<input type='hidden'>"),
            mode="games",
        )
    )


def _selection_overflow() -> str:
    return str(
        _selection_actions_slot(
            [{"label": "Remove", "url": "/remove/", "color": "red"}],
            "token",
            id_seed="seed",
        )
    )


SITES = {
    "menu": lambda: str(DropdownMenuPanel(items=[DropdownActionItem()["Go"]])),
    "listbox": lambda: str(ListboxPanel(options=[SelectOption("a", "A", True)])),
    "combobox": lambda: str(
        ComboboxDropdown(label="Pick", content=Span()["x"], id="pick")
    ),
    "column picker": _column_picker,
    "selection overflow": _selection_overflow,
}


@pytest.mark.parametrize("site", SITES)
def test_the_panel_is_a_still_surface_around_one_scroller(site):
    [panel] = _panels(SITES[site]())

    classes = panel["attributes"]["class"].split()
    assert len(panel["children"]) == 1
    assert "overflow-y-auto" not in classes
    assert {"flex", "flex-col", "isolate", "border", "shadow-sm"} <= set(classes)
    [scroller] = panel["children"]
    assert {"min-h-0", "overflow-y-auto"} <= set(
        scroller["attributes"]["class"].split()
    )


def test_the_quick_overflow_moves_facets_into_the_scroller():
    presentation = DateTimePresentation(
        DEFAULT_DATE_TIME_FORMAT_PROFILE, "en-us", ZoneInfo("UTC")
    )
    html = str(QuickFilterBar(mode="games", presentation=presentation))
    [panel] = [
        panel
        for panel in _panels(html)
        if panel["attributes"].get("aria-label") == "More filters"
    ]
    [scroller] = panel["children"]
    assert "data-quick-overflow-items" in scroller["attributes"]


def test_the_selection_overflow_moves_acts_into_the_scroller():
    [panel] = _panels(_selection_overflow())
    [scroller] = panel["children"]
    assert "data-selection-overflow-items" in scroller["attributes"]
    assert "data-selection-overflow-items" not in panel["attributes"]


def test_content_attributes_and_class_reach_the_scroller():
    html = str(
        DropdownPanel(
            role="dialog",
            width="w-44",
            content_attributes=[("role", "listbox")],
            content_class="max-h-40",
        )["x"]
    )
    [panel] = _panels(html)
    [scroller] = panel["children"]
    assert panel["attributes"]["role"] == "dialog"
    assert "w-44" in panel["attributes"]["class"].split()
    assert scroller["attributes"]["role"] == "listbox"
    assert "max-h-40" in scroller["attributes"]["class"].split()


def test_every_state_spells_the_one_active_look():
    from common.components import custom_elements

    for variant, spelled in [
        ("hover", custom_elements._ITEM_ACTIVE_ON_HOVER),
        ("focus", custom_elements._ITEM_ACTIVE_ON_FOCUS),
    ]:
        expected = [f"{variant}:{token}" for token in DROPDOWN_ITEM_ACTIVE.split()]
        assert spelled.split() == expected
